import uuid

from django.core.cache import cache
from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.limiter import (
    _last_written,
    _observed_memo,
    _tier_budgets,
    get_observed_core_limit,
    github_installation_key,
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
            assert _tier_budgets(15_000) == (13_500, 150)  # floor still applies, but capped by the knob's intent
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
