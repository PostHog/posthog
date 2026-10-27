from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.api.query import required_scopes_for_query_payload
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import hash_key_value

SAMPLE_QUERY = {"kind": "HogQLQuery", "query": "SELECT 1"}
_UNSET = object()


def _make_psak(team, label="psak", scopes=_UNSET):
    # The token must match _SECRET_API_KEY_RE = r"^phs_[a-zA-Z0-9]+$".
    suffix = "".join(c for c in label if c.isalnum())
    token = "phs_" + ("a" * 35) + suffix
    psak = ProjectSecretAPIKey.objects.create(
        team=team,
        label=label,
        mask_value=f"phs_...{suffix[:4]}",
        secure_value=hash_key_value(token),
        scopes=["query:read"] if scopes is _UNSET else scopes,
    )
    return token, psak


def test_product_query_kinds_require_a_scope_a_project_secret_key_cannot_hold():
    # Scope composition, not a deny-list, is what keeps a service key out of the product query
    # kinds: each one needs the product's own scope, and a PSAK may hold none of them.
    assert required_scopes_for_query_payload({"kind": "MetricsQuery"}) == ["metrics:read"]


def _auth_headers(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class TestQueryViewSetPSAKAuth(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.logout()
        self.query_url = f"/api/projects/{self.team.id}/query/"

    def test_psak_can_run_a_query(self):
        token, _ = _make_psak(self.team, label="run-key")

        response = self.client.post(
            self.query_url,
            {"query": SAMPLE_QUERY},
            content_type="application/json",
            **_auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["results"], [[1]])

    def test_psak_can_run_an_insight_query(self):
        # Insight runners resolve the caller's table access and cache partition from `user`, and a
        # service key is a principal those paths have to carry without a user row.
        _create_event(team=self.team, event="signed up", distinct_id="person-1")
        flush_persons_and_events()
        token, _ = _make_psak(self.team, label="events-key")

        response = self.client.post(
            self.query_url,
            {"query": {"kind": "EventsQuery", "select": ["event"], "limit": 10}},
            content_type="application/json",
            **_auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual([row[0] for row in response.json()["results"]], ["signed up"])

    @parameterized.expand(
        [
            ("session", None, False),
            ("psak", "psak-billing-key", True),
        ]
    )
    def test_only_api_key_callers_spend_the_api_query_budget(self, _name, psak_label, expected):
        # A service key is a programmatic caller, so its queries are billed as API queries the same
        # way a personal key's are; a logged-in browser session keeps taking the web path.
        if psak_label is None:
            self.client.force_login(self.user)
            headers = {}
        else:
            token, _ = _make_psak(self.team, label=psak_label)
            headers = _auth_headers(token)

        with patch(
            "posthog.api.query.process_query_model", return_value={"results": [], "is_cached": False}
        ) as process_query_model:
            response = self.client.post(
                self.query_url,
                {"query": SAMPLE_QUERY},
                content_type="application/json",
                **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertIs(process_query_model.call_args.kwargs["is_query_service"], expected)

    @parameterized.expand(
        [
            ("retrieve", "GET", "some-query-id/"),
            ("destroy", "DELETE", "some-query-id/"),
            ("draft_sql", "GET", "draft_sql/"),
            ("check_auth_for_async", "POST", "check_auth_for_async/"),
        ]
    )
    def test_psak_blocked_on_non_create_actions(self, _name, method, path_suffix):
        token, _ = _make_psak(self.team, label=f"non-create-{_name}")

        response = self.client.generic(
            method,
            f"{self.query_url}{path_suffix}",
            **_auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertIn("does not support project secret API key", response.json().get("detail", ""))

    @parameterized.expand([("empty_list", []), ("null", None)])
    def test_psak_without_query_scope_returns_403(self, _name, scopes):
        # A key that holds no query scope must not run queries even though the action is allowed.
        token, _ = _make_psak(self.team, label=f"no-query-scope-{_name}", scopes=scopes)

        response = self.client.post(
            self.query_url,
            {"query": SAMPLE_QUERY},
            content_type="application/json",
            **_auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertIn("missing required scope 'query:read'", response.json().get("detail", ""))

    @parameterized.expand([("force_async", {"refresh": "force_async"}), ("legacy_async", {"async": True})])
    def test_psak_requires_synchronous_queries(self, _name, extra_body):
        token, _ = _make_psak(self.team, label=f"async-{_name}")

        response = self.client.post(
            self.query_url,
            {"query": SAMPLE_QUERY, **extra_body},
            content_type="application/json",
            **_auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn("run queries synchronously", response.json().get("detail", ""))

    def test_session_auth_still_works(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.query_url,
            {"query": SAMPLE_QUERY},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


@patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
@patch("posthog.rate_limit.QueryHogQLThrottle.rate", new="2/minute")
class TestQueryPSAKRateLimit(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.logout()
        self.query_url = f"/api/projects/{self.team.id}/query/"
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _run(self, token: str | None = None):
        headers = _auth_headers(token) if token else {}
        return self.client.post(
            self.query_url,
            {"query": SAMPLE_QUERY},
            content_type="application/json",
            **headers,
        )

    def test_psak_requests_are_throttled(self, *_args):
        token, _ = _make_psak(self.team, label="rl-key")

        for _ in range(2):
            self.assertEqual(self._run(token).status_code, status.HTTP_200_OK)

        self.assertEqual(self._run(token).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_a_second_key_cannot_spend_more_of_the_project_budget(self, *_args):
        # The project budget is one key's budget, so minting extra keys must not multiply it.
        token_a, _a = _make_psak(self.team, label="team-key-a")
        token_b, _b = _make_psak(self.team, label="team-key-b")

        self.assertEqual(self._run(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._run(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._run(token_b).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_project_budget_follows_the_teams_query_rate_limit(self, *_args):
        # The project cap has to come from the same rate the branch meters one key with, including
        # a team's own override, or the cap silently outruns what a key may spend.
        self.team.api_query_rate_limit = "2/minute"
        self.team.save(update_fields=["api_query_rate_limit"])
        token_a, _a = _make_psak(self.team, label="override-key-a")
        token_b, _b = _make_psak(self.team, label="override-key-b")

        self.assertEqual(self._run(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._run(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._run(token_b).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_session_user_is_not_throttled(self, *_args):
        self.client.force_login(self.user)

        for _ in range(4):
            self.assertEqual(self._run().status_code, status.HTTP_200_OK)
