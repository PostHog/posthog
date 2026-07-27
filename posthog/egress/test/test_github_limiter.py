import uuid

from django.core.cache import cache
from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.limiter import (
    GitHubRateResource,
    _last_written,
    _observed_memo,
    _tier_budgets,
    classify_github_resource,
    get_observed_core_limit,
    github_installation_key,
    installation_id_from_key,
    observed_core_limit_cache_key,
    remember_observed_core_limit,
)
from posthog.egress.limiter.policies import Priority, resolve_policy


def _response(*, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict(headers or {})
    return response


def _core_headers(limit: str) -> dict[str, str]:
    return {"X-RateLimit-Resource": "core", "X-RateLimit-Limit": limit}


class GitHubLimiterTestCase(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        _observed_memo.clear()
        _last_written.clear()
        self.installation_id = f"test-{uuid.uuid4().hex[:8]}"
        self.addCleanup(cache.delete, observed_core_limit_cache_key(self.installation_id))
        self.addCleanup(_observed_memo.clear)
        self.addCleanup(_last_written.clear)


class TestGitHubTierBudgets(GitHubLimiterTestCase):
    # Guards the tier math: if the 90% derivation, the /18 minute scaling, the clamps, or the
    # settings-as-ceiling contract regress, 5k-tier installations get budgeted above their real
    # GitHub limit (the limiter never fires) or the operator's emergency knob stops reaching traffic.
    @parameterized.expand(
        [
            ("unobserved_uses_defaults", None, 13_500, 750),
            ("five_k_tier", 5_000, 4_500, 250),
            ("top_tier", 15_000, 13_500, 750),
            ("tiny_tier_hits_minute_floor", 1_000, 900, 150),
            ("huge_tier_capped_at_default", 50_000, 13_500, 750),
        ]
    )
    def test_tier_budgets(self, _name: str, observed: int | None, expected_hourly: int, expected_minute: int) -> None:
        assert _tier_budgets(observed) == (expected_hourly, expected_minute)

    def test_per_minute_setting_is_a_ceiling_for_observed_tiers_too(self) -> None:
        with self.settings(GITHUB_EGRESS_PER_MINUTE_BUDGET=100):
            assert _tier_budgets(15_000) == (13_500, 100)  # a setting below the burst floor still wins
        with self.settings(GITHUB_EGRESS_PER_MINUTE_BUDGET=200):
            assert _tier_budgets(15_000) == (13_500, 200)

    def test_policy_reads_observed_tier_for_the_keys_installation(self) -> None:
        # Guards the wiring: key parsing + tier read + reserve attach. If resolve_policy stops
        # passing the key, or the store's key drifts from the writer's, every installation silently
        # falls back to the flat default budget and the reserve ladder detaches.
        cache.set(observed_core_limit_cache_key(self.installation_id), 5_000, 60)

        policy = resolve_policy(github_installation_key(self.installation_id))

        assert policy.limits == ((250, 60.0), (4_500, 3600.0))
        assert policy.reserve_fraction(Priority.BATCH) > policy.reserve_fraction(Priority.NORMAL) > 0.0
        assert policy.reserve_fraction(Priority.CRITICAL) == 0.0


class TestObservedCoreLimitStore(GitHubLimiterTestCase):
    # Guards the trusted-observation filter: responses from other principals sharing the
    # installation id (App-JWT refreshes, user-token calls via their error statuses, an
    # unauthenticated 401's 60-limit) must never feed the budget — a poisoned tier either clamps
    # the installation to a fictional budget for days or crashes the limiter's validation.
    def test_successful_core_observation_round_trips(self) -> None:
        remember_observed_core_limit(self.installation_id, _response(headers=_core_headers("5000")))
        assert get_observed_core_limit(self.installation_id) == 5000

    @parameterized.expand(
        [
            ("non_core_resource", 200, {"X-RateLimit-Resource": "graphql", "X-RateLimit-Limit": "5000"}),
            ("missing_resource_header", 200, {"X-RateLimit-Limit": "5000"}),
            ("error_response", 401, _core_headers("60")),
            ("implausibly_small_limit", 200, _core_headers("60")),
            ("missing_limit_header", 200, {"X-RateLimit-Resource": "core"}),
        ]
    )
    def test_untrusted_observations_are_ignored(self, _name: str, status: int, headers: dict[str, str]) -> None:
        remember_observed_core_limit(self.installation_id, _response(status=status, headers=headers))
        assert get_observed_core_limit(self.installation_id) is None

    @parameterized.expand(
        [
            ("bool_is_not_a_limit", True),
            ("garbage_small_int", 60),
            ("wrong_type", "5000"),
        ]
    )
    def test_junk_cached_values_fall_back_to_defaults(self, _name: str, cached: object) -> None:
        # A bad value must degrade to the defaults, never crash admission (a tiny limit would make
        # the policy's window smaller than a single call and raise on every acquire, CRITICAL included).
        cache.set(observed_core_limit_cache_key(self.installation_id), cached, 60)
        assert get_observed_core_limit(self.installation_id) is None


class TestClassifyGithubResource(SimpleTestCase):
    # The routing that this whole fix hinges on: a /search/code call charged to core would sail
    # through the 5k/hour budget while GitHub 403/429s it at 10/min. Guards that each URL lands on
    # the resource GitHub actually meters it against.
    @parameterized.expand(
        [
            ("code_search_full_url", "https://api.github.com/search/code?q=x", GitHubRateResource.CODE_SEARCH),
            ("code_search_bare_path", "/search/code", GitHubRateResource.CODE_SEARCH),
            ("search_issues", "/search/issues", GitHubRateResource.SEARCH),
            ("search_repositories", "/search/repositories?q=x", GitHubRateResource.SEARCH),
            ("core_repo_call", "/repos/o/r/pulls/1", GitHubRateResource.CORE),
            ("graphql_routes_to_core", "/graphql", GitHubRateResource.CORE),
            ("access_tokens_is_core", "/app/installations/1/access_tokens", GitHubRateResource.CORE),
        ]
    )
    def test_classify(self, _name: str, url: str, expected: GitHubRateResource) -> None:
        assert classify_github_resource(url) == expected


class TestSearchResourcePolicies(SimpleTestCase):
    # The static search budgets and the reserve ladder attach: a regression here silently reverts
    # /search/code to the flat core budget (the bug this fix closes) or drops the shedding ladder.
    @parameterized.expand(
        [
            ("code_search", GitHubRateResource.CODE_SEARCH, (8, 60.0)),
            ("search", GitHubRateResource.SEARCH, (27, 60.0)),
        ]
    )
    def test_static_policy_and_reserve_ladder(
        self, _name: str, resource: GitHubRateResource, expected_limit: tuple[int, float]
    ) -> None:
        policy = resolve_policy(github_installation_key("x", resource=resource))
        assert policy.limits == (expected_limit,)
        assert policy.reserve_fraction(Priority.BATCH) > policy.reserve_fraction(Priority.NORMAL) > 0.0
        assert policy.reserve_fraction(Priority.CRITICAL) == 0.0


class TestInstallationKeyResource(SimpleTestCase):
    # The resource -> domain mapping plus the key round-trip: a broken mapping keys the wrong meter,
    # and a broken round-trip means the tier lookup reads the wrong installation.
    @parameterized.expand(
        [
            ("core", GitHubRateResource.CORE, "github"),
            ("search", GitHubRateResource.SEARCH, "github_search"),
            ("code_search", GitHubRateResource.CODE_SEARCH, "github_code_search"),
        ]
    )
    def test_key_domain_and_round_trip(self, _name: str, resource: GitHubRateResource, expected_domain: str) -> None:
        key = github_installation_key(42, resource=resource)
        assert key.split(":")[0] == expected_domain
        assert installation_id_from_key(key) == "42"
