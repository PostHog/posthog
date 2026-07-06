"""Tests for the personal LLM spend analysis API endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

ENDPOINT = "/api/llm_analytics/@me/spend/"
# `product` is required server-side; spell that out once for every happy-path test.
PRODUCT_QS = "product=posthog_code"
ENDPOINT_OK = f"{ENDPOINT}?{PRODUCT_QS}"


def _by_product(rows: list[dict], product: str | None) -> dict | None:
    return next((r for r in rows if r["product"] == product), None)


class TestPersonalSpendEuRedirect(APIBaseTest):
    """Pure unit test of the EU redirect view — does not depend on URL conf for EU."""

    def test_eu_redirect_view_preserves_query_string(self) -> None:
        from django.test import RequestFactory

        from products.ai_observability.backend.api.personal_spend import personal_spend_eu_redirect

        factory = RequestFactory()
        request = factory.get("/api/llm_analytics/@me/spend/", data={"date_from": "-7d", "product": "posthog_code"})
        response = personal_spend_eu_redirect(request)

        assert response.status_code == status.HTTP_302_FOUND
        assert response["Location"].startswith("https://us.posthog.com/api/llm_analytics/@me/spend/")
        assert "date_from=-7d" in response["Location"]
        assert "product=posthog_code" in response["Location"]

    def test_eu_redirect_view_strips_unknown_params(self) -> None:
        from django.test import RequestFactory

        from products.ai_observability.backend.api.personal_spend import personal_spend_eu_redirect

        factory = RequestFactory()
        request = factory.get(
            "/api/llm_analytics/@me/spend/",
            data={"date_from": "-7d", "evil": "https://attacker.example/", "fragment": "#"},
        )
        response = personal_spend_eu_redirect(request)

        assert response.status_code == status.HTTP_302_FOUND
        # Target host stays hardcoded.
        assert response["Location"].startswith("https://us.posthog.com/")
        # Allowed param preserved.
        assert "date_from=-7d" in response["Location"]
        # Unknown params dropped (allowlist enforced).
        assert "evil" not in response["Location"]
        assert "fragment" not in response["Location"]
        assert "attacker.example" not in response["Location"]


class TestPersonalSpendAuth(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id)
        self._team_id_override.enable()
        self.addCleanup(self._team_id_override.disable)

    def test_unauthenticated_caller_rejected(self) -> None:
        self.client.logout()
        response = self.client.get(ENDPOINT)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_caller_without_email_rejected(self) -> None:
        self.user.email = ""
        self.user.save()
        response = self.client.get(ENDPOINT)
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestPersonalSpendValidation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id)
        self._team_id_override.enable()
        self.addCleanup(self._team_id_override.disable)

    @parameterized.expand(
        [
            ("nonsense", "wibble", status.HTTP_400_BAD_REQUEST),
            ("over_max_window", "-365d", status.HTTP_400_BAD_REQUEST),
            ("valid_relative_short", "-1d", status.HTTP_200_OK),
            ("valid_relative_default", "-30d", status.HTTP_200_OK),
            ("valid_relative_max", "-90d", status.HTTP_200_OK),
        ]
    )
    def test_date_from_param_validation(self, _label: str, date_from: str, expected: int) -> None:
        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from={date_from}")
        assert response.status_code == expected

    def test_date_params_default_to_last_30_days(self) -> None:
        response = self.client.get(ENDPOINT_OK)
        assert response.status_code == status.HTTP_200_OK
        summary = response.json()["summary"]
        assert summary["product"] == "posthog_code"
        # date_from / date_to are returned as ISO strings.
        assert summary["date_from"] is not None
        assert summary["date_to"] is not None

    def test_date_to_before_date_from_rejected(self) -> None:
        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=-7d&date_to=-30d")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_product_too_long_rejected(self) -> None:
        response = self.client.get(f"{ENDPOINT}?product={'x' * 100}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_product_param_required(self) -> None:
        response = self.client.get(ENDPOINT)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["attr"] == "product"
        assert body["code"] == "required"

    @parameterized.expand(
        [
            ("supported_posthog_code", "posthog_code", status.HTTP_200_OK),
            ("unsupported_background_agents", "background_agents", status.HTTP_400_BAD_REQUEST),
            ("unsupported_arbitrary", "wibble", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_product_param_restricted_to_supported_products(self, _label: str, product: str, expected: int) -> None:
        response = self.client.get(f"{ENDPOINT}?product={product}")
        assert response.status_code == expected
        if expected == status.HTTP_400_BAD_REQUEST:
            body = response.json()
            assert "is not supported" in str(body)

    @parameterized.expand(
        [
            ("zero", "0", status.HTTP_400_BAD_REQUEST),
            ("negative", "-1", status.HTTP_400_BAD_REQUEST),
            ("over_max", "1000", status.HTTP_400_BAD_REQUEST),
            ("valid_min", "1", status.HTTP_200_OK),
            ("valid_default", "50", status.HTTP_200_OK),
            ("valid_max", "200", status.HTTP_200_OK),
        ]
    )
    def test_limit_param_validation(self, _label: str, limit: str, expected: int) -> None:
        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&limit={limit}")
        assert response.status_code == expected


class TestPersonalSpendQueries(ClickhouseTestMixin, APIBaseTest):
    """End-to-end tests against ClickHouse with real $ai_generation events."""

    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id)
        self._team_id_override.enable()
        self.addCleanup(self._team_id_override.disable)

        _create_person(
            distinct_ids=[self.user.distinct_id or self.user.email],
            team=self.team,
            properties={"email": self.user.email},
        )
        flush_persons_and_events()

    def _create_generation(
        self,
        *,
        ai_product: str = "posthog_code",
        model: str = "claude-opus-4-8",
        tool: str | None = "Bash",
        trace_id: str = "trace-1",
        cost: float | None = 1.5,
        input_tokens: int = 100000,
        output_tokens: int = 500,
        event_name: str = "$ai_generation",
        timestamp: datetime | None = None,
    ) -> None:
        props: dict = {
            "$ai_input_tokens": input_tokens,
            "$ai_output_tokens": output_tokens,
            "$ai_model": model,
            "$ai_trace_id": trace_id,
            "ai_product": ai_product,
        }
        if cost is not None:
            props["$ai_total_cost_usd"] = cost
        if tool is not None:
            props["$ai_tools_called"] = tool
        kwargs: dict = {}
        if timestamp is not None:
            kwargs["timestamp"] = timestamp
        _create_event(
            event=event_name,
            team=self.team,
            distinct_id=self.user.distinct_id or self.user.email,
            properties=props,
            **kwargs,
        )

    @snapshot_clickhouse_queries
    def test_empty_result_when_no_events(self) -> None:
        response = self.client.get(ENDPOINT_OK)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["summary"]["total_cost_usd"] == 0
        assert body["summary"]["event_count"] == 0
        assert body["summary"]["scoped_cost_usd"] == 0
        assert body["summary"]["scoped_event_count"] == 0
        assert body["by_product"] == {"items": [], "truncated": False}
        assert body["by_tool"] == {"items": [], "truncated": False}
        assert body["by_model"] == {"items": [], "truncated": False}
        assert body["by_day"] == {"items": [], "truncated": False}
        assert body["top_traces"] == {"items": [], "truncated": False}

    def test_summary_reports_cross_product_totals_alongside_scoped(self) -> None:
        self._create_generation(ai_product="posthog_code", cost=2.0)
        self._create_generation(ai_product="background_agents", cost=1.0)
        self._create_generation(ai_product="posthog_code", cost=0.5, event_name="$ai_embedding")
        flush_persons_and_events()

        response = self.client.get(ENDPOINT_OK)
        body = response.json()
        summary = body["summary"]
        assert summary["product"] == "posthog_code"
        # `event_count` / `total_cost_usd` stay cross-product even with the product filter.
        assert summary["event_count"] == 3
        assert summary["total_cost_usd"] == 3.5
        # `scoped_*` is filtered to posthog_code only.
        assert summary["scoped_event_count"] == 2
        assert summary["scoped_cost_usd"] == 2.5
        # by_product is always cross-product regardless of the filter.
        code_row = _by_product(body["by_product"]["items"], "posthog_code")
        assert code_row is not None
        assert code_row["cost_usd"] == 2.5
        bg_row = _by_product(body["by_product"]["items"], "background_agents")
        assert bg_row is not None
        assert bg_row["cost_usd"] == 1.0
        assert body["by_product"]["truncated"] is False

    def test_product_filter_scopes_summary_and_breakdowns(self) -> None:
        self._create_generation(ai_product="posthog_code", tool="Bash", cost=2.0)
        self._create_generation(ai_product="background_agents", tool="Bash", cost=10.0)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        body = response.json()

        # Summary still reports cross-product totals; scoped_* is filtered.
        assert body["summary"]["product"] == "posthog_code"
        assert body["summary"]["total_cost_usd"] == 12.0
        assert body["summary"]["scoped_cost_usd"] == 2.0

        # by_tool is scoped to the filter — only the posthog_code Bash row.
        tool_rows = body["by_tool"]["items"]
        assert len(tool_rows) == 1
        assert tool_rows[0]["cost_usd"] == 2.0
        assert tool_rows[0]["share_of_scoped"] == 1.0

        # by_product is always cross-product, regardless of the filter.
        assert {r["product"] for r in body["by_product"]["items"]} == {"posthog_code", "background_agents"}

    def test_by_tool_includes_null_tool_rows(self) -> None:
        self._create_generation(tool="Bash", cost=2.0)
        self._create_generation(tool=None, cost=0.5)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        tools = {r["tool"] for r in response.json()["by_tool"]["items"]}
        assert tools == {"Bash", None}

    def test_by_tool_splits_comma_separated_tools(self) -> None:
        # One generation that calls Bash and Read should contribute to both rows.
        self._create_generation(tool="Bash,Read", cost=2.0, trace_id="multi")
        # One single-tool generation that also touches Bash, plus a single-tool Read.
        self._create_generation(tool="Bash", cost=1.0, trace_id="bash-only")
        self._create_generation(tool="Read", cost=0.5, trace_id="read-only")
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        rows = {r["tool"]: r for r in response.json()["by_tool"]["items"]}
        assert set(rows) == {"Bash", "Read"}
        # Bash row picks up both the Bash-only generation and the Bash,Read generation.
        assert rows["Bash"]["generation_count"] == 2
        assert rows["Bash"]["cost_usd"] == 3.0
        # Read row picks up both the Read-only generation and the Bash,Read generation.
        assert rows["Read"]["generation_count"] == 2
        assert rows["Read"]["cost_usd"] == 2.5
        # Scoped total stays $3.50 — the multi-tool generation is only counted once there.
        assert response.json()["summary"]["scoped_cost_usd"] == 3.5

    def test_top_traces_always_empty(self) -> None:
        # `top_traces` is deprecated — kept in the response shape so existing consumers don't
        # crash, but always returns empty. Trace IDs are opaque strings that aren't actionable
        # in the UI.
        self._create_generation(trace_id="cheap", cost=0.5)
        self._create_generation(trace_id="expensive", cost=5.0)
        flush_persons_and_events()

        response = self.client.get(ENDPOINT_OK)
        assert response.json()["top_traces"] == {"items": [], "truncated": False}

    def test_other_users_spend_is_not_visible(self) -> None:
        other_email = "other-user@example.com"
        _create_person(distinct_ids=["other-distinct"], team=self.team, properties={"email": other_email})
        _create_event(
            event="$ai_generation",
            team=self.team,
            distinct_id="other-distinct",
            properties={
                "$ai_total_cost_usd": 999.99,
                "ai_product": "posthog_code",
                "$ai_model": "claude-opus-4-8",
                "$ai_tools_called": "Bash",
                "$ai_trace_id": "their-trace",
            },
        )
        self._create_generation(cost=1.0)
        flush_persons_and_events()

        response = self.client.get(ENDPOINT_OK)
        assert response.json()["summary"]["total_cost_usd"] == 1.0

    def test_date_window_passes_through_to_query_layer(self) -> None:
        with patch("products.ai_observability.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=-7d")

        assert response.status_code == status.HTTP_200_OK
        # 5 fetchers run once (summary, by_product, by_tool, by_model, by_day). top_traces
        # is deprecated and returned empty without a query.
        assert mock_exec.call_count == 5

    def test_second_call_serves_from_cache(self) -> None:
        with patch("products.ai_observability.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(ENDPOINT_OK)
            first = mock_exec.call_count
            self.client.get(ENDPOINT_OK)
            assert mock_exec.call_count == first

    def test_refresh_bypasses_cache(self) -> None:
        with patch("products.ai_observability.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(ENDPOINT_OK)
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&refresh=true")
            assert mock_exec.call_count == first * 2

    def test_cache_key_includes_date_from(self) -> None:
        with patch("products.ai_observability.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=-7d")
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=-30d")
            assert mock_exec.call_count == first * 2

    def test_cache_key_includes_limit(self) -> None:
        with patch("products.ai_observability.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&limit=10")
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&limit=50")
            assert mock_exec.call_count == first * 2

    def test_by_product_truncated_when_more_than_limit_products(self) -> None:
        # Three products, ask for limit=2 → top 2 returned, truncated=True.
        # by_product is cross-product even when filtered, so the additional
        # ai_products still show up.
        self._create_generation(ai_product="a", cost=3.0)
        self._create_generation(ai_product="b", cost=2.0)
        self._create_generation(ai_product="c", cost=1.0)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&limit=2")
        by_product = response.json()["by_product"]
        assert len(by_product["items"]) == 2
        assert by_product["truncated"] is True

    def test_by_tool_share_of_scoped(self) -> None:
        self._create_generation(tool="Bash", cost=2.0)
        self._create_generation(tool="Read", cost=2.0)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        rows = {r["tool"]: r for r in response.json()["by_tool"]["items"]}
        # Each tool drove half of the scoped spend.
        assert rows["Bash"]["share_of_scoped"] == 0.5
        assert rows["Read"]["share_of_scoped"] == 0.5

    def test_by_day_groups_spend_per_utc_day_scoped_to_product(self) -> None:
        earlier = datetime(2026, 6, 13, 9, 0, tzinfo=UTC)
        later = datetime(2026, 6, 15, 20, 0, tzinfo=UTC)
        self._create_generation(cost=1.0, trace_id="old-1", timestamp=earlier)
        self._create_generation(cost=0.5, trace_id="old-2", timestamp=earlier)
        self._create_generation(cost=2.0, trace_id="new", timestamp=later)
        # Same day as `earlier` but another product: must not leak into the scoped series.
        self._create_generation(ai_product="background_agents", cost=99.0, timestamp=earlier)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=2026-06-10&date_to=2026-06-16")
        by_day = response.json()["by_day"]
        assert by_day["truncated"] is False
        # Ordered by day ascending, not by cost.
        assert by_day["items"] == [
            {"day": "2026-06-13", "event_count": 2, "cost_usd": 1.5},
            {"day": "2026-06-15", "event_count": 1, "cost_usd": 2.0},
        ]

    def test_by_day_ignores_request_limit(self) -> None:
        self._create_generation(cost=1.0, trace_id="a", timestamp=datetime(2026, 6, 12, 12, 0, tzinfo=UTC))
        self._create_generation(cost=2.0, trace_id="b", timestamp=datetime(2026, 6, 13, 12, 0, tzinfo=UTC))
        self._create_generation(cost=3.0, trace_id="c", timestamp=datetime(2026, 6, 14, 12, 0, tzinfo=UTC))
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=2026-06-10&date_to=2026-06-16&limit=1")
        body = response.json()
        # by_model honors the limit; by_day returns the full series regardless.
        assert len(body["by_day"]["items"]) == 3
        assert body["by_day"]["truncated"] is False

    def test_by_day_uses_utc_days_regardless_of_team_timezone(self) -> None:
        self.team.timezone = "Asia/Tokyo"
        self.team.save()
        # 20:00 UTC on Jun 15 is already Jun 16 in Tokyo; the bucket must stay on the UTC day.
        self._create_generation(cost=1.0, timestamp=datetime(2026, 6, 15, 20, 0, tzinfo=UTC))
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=2026-06-10&date_to=2026-06-16")
        assert [r["day"] for r in response.json()["by_day"]["items"]] == ["2026-06-15"]

    def test_by_day_counts_embeddings_and_costless_events(self) -> None:
        day_one = datetime(2026, 6, 13, 9, 0, tzinfo=UTC)
        self._create_generation(cost=1.0, timestamp=day_one)
        self._create_generation(cost=0.5, event_name="$ai_embedding", timestamp=day_one)
        # A generation captured without `$ai_total_cost_usd` must count but cost nothing.
        self._create_generation(cost=None, timestamp=datetime(2026, 6, 15, 12, 0, tzinfo=UTC))
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=2026-06-10&date_to=2026-06-16")
        assert response.json()["by_day"]["items"] == [
            {"day": "2026-06-13", "event_count": 2, "cost_usd": 1.5},
            {"day": "2026-06-15", "event_count": 1, "cost_usd": 0.0},
        ]


class TestPersonalSpendNonSessionAuth(APIBaseTest):
    """
    Pins down what scopes the MCP and OAuth-token paths need to reach
    `/api/llm_analytics/@me/spend/`. The endpoint is `scope_object = "user"` —
    same bucket as `/api/users/@me/` — so the wildcard `*` (the "Full access"
    consent option) and an explicit `user:read` both grant access. An OAuth
    token carrying only OIDC identity scopes (`openid profile email`) without
    any resource scope is correctly rejected: identity alone does not imply
    permission to read account data.
    """

    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id)
        self._team_id_override.enable()
        self.addCleanup(self._team_id_override.disable)
        self.client.logout()

    def _make_pat(self, scopes: list[str]) -> str:
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="spend-test",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=scopes,
        )
        return raw

    def _make_oauth_token(self, scope: str) -> str:
        app = OAuthApplication.objects.create(
            name="MCP-like client",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/cb",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )
        token_value = f"pha_test_{generate_random_token_personal()[:24]}"
        OAuthAccessToken.objects.create(
            user=self.user,
            application=app,
            token=token_value,
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
        )
        return token_value

    @parameterized.expand(
        [
            ("wildcard_pat", ["*"], status.HTTP_200_OK),
            ("user_read_pat", ["user:read"], status.HTTP_200_OK),
            ("unrelated_scope_pat", ["insight:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_personal_api_key_scope_matrix(self, _label: str, scopes: list[str], expected: int) -> None:
        token = self._make_pat(scopes)
        response = self.client.get(ENDPOINT_OK, headers={"authorization": f"Bearer {token}"})
        assert response.status_code == expected, response.content

    @parameterized.expand(
        [
            ("wildcard_oauth", "*", status.HTTP_200_OK),
            ("user_read_oauth", "user:read", status.HTTP_200_OK),
            ("oidc_only_rejected", "openid profile email", status.HTTP_403_FORBIDDEN),
            ("unrelated_scope_rejected", "insight:read", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_oauth_token_scope_matrix(self, _label: str, scope: str, expected: int) -> None:
        token = self._make_oauth_token(scope)
        response = self.client.get(ENDPOINT_OK, headers={"authorization": f"Bearer {token}"})
        assert response.status_code == expected, response.content
