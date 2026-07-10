"""Tests for the personal LLM spend analysis API endpoint."""

from __future__ import annotations

import json
import time
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

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.ai_observability.backend.api.personal_spend import (
    CROSS_REGION_SIGNATURE_HEADER,
    CROSS_REGION_TIMESTAMP_HEADER,
    PersonalSpendEUProxyViewSet,
    sign_cross_region_spend_request,
)

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

    @parameterized.expand(
        [
            ("hourly_within_cap", 60, "-7d", status.HTTP_200_OK),
            ("hourly_over_cap", 60, "-30d", status.HTTP_400_BAD_REQUEST),
            ("five_min_within_cap", 5, "-1d", status.HTTP_200_OK),
            ("five_min_over_cap", 5, "-7d", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_bucket_window_cap(self, _label: str, bucket_minutes: int, date_from: str, expected: int) -> None:
        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from={date_from}&bucket_minutes={bucket_minutes}")
        assert response.status_code == expected

    def test_unsupported_bucket_size_rejected(self) -> None:
        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&bucket_minutes=7")
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
        extra_props: dict | None = None,
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
        if extra_props:
            props.update(extra_props)
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

    def test_by_bucket_absent_unless_requested(self) -> None:
        response = self.client.get(ENDPOINT_OK)
        assert response.status_code == status.HTTP_200_OK
        assert "by_bucket" not in response.json()

    def test_by_bucket_groups_cost_components_per_utc_hour(self) -> None:
        warm = datetime(2026, 6, 15, 9, 30, tzinfo=UTC)
        cold = datetime(2026, 6, 15, 11, 5, tzinfo=UTC)
        # Warm turn: most of the prompt served from cache.
        self._create_generation(
            cost=1.0,
            trace_id="warm",
            timestamp=warm,
            input_tokens=1000,
            output_tokens=500,
            extra_props={
                "$ai_input_cost_usd": 0.1,
                "$ai_output_cost_usd": 0.2,
                "$ai_cache_read_cost_usd": 0.6,
                "$ai_cache_creation_cost_usd": 0.1,
                "$ai_cache_read_input_tokens": 400000,
                "$ai_cache_creation_input_tokens": 20000,
            },
        )
        # Cold-revival turn: the whole context re-written to cache, nothing read back.
        self._create_generation(
            cost=3.0,
            trace_id="cold",
            timestamp=cold,
            input_tokens=2000,
            output_tokens=800,
            extra_props={
                "$ai_input_cost_usd": 0.2,
                "$ai_output_cost_usd": 0.3,
                "$ai_cache_read_cost_usd": 0.0,
                "$ai_cache_creation_cost_usd": 2.5,
                "$ai_cache_read_input_tokens": 0,
                "$ai_cache_creation_input_tokens": 500000,
            },
        )
        # Same hour, another product: must not leak into the scoped series.
        self._create_generation(ai_product="background_agents", cost=99.0, timestamp=cold)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=2026-06-15&date_to=2026-06-16&bucket_minutes=60")
        by_bucket = response.json()["by_bucket"]
        assert by_bucket["truncated"] is False
        assert by_bucket["bucket_minutes"] == 60
        assert by_bucket["items"] == [
            {
                "bucket_start": "2026-06-15T09:00:00Z",
                "event_count": 1,
                "cost_usd": 1.0,
                "input_cost_usd": 0.1,
                "output_cost_usd": 0.2,
                "cache_read_cost_usd": 0.6,
                "cache_creation_cost_usd": 0.1,
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 400000,
                "cache_creation_input_tokens": 20000,
            },
            {
                "bucket_start": "2026-06-15T11:00:00Z",
                "event_count": 1,
                "cost_usd": 3.0,
                "input_cost_usd": 0.2,
                "output_cost_usd": 0.3,
                "cache_read_cost_usd": 0.0,
                "cache_creation_cost_usd": 2.5,
                "input_tokens": 2000,
                "output_tokens": 800,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 500000,
            },
        ]

    def test_by_bucket_five_minute_buckets_split_within_the_hour(self) -> None:
        # Two calls 15 minutes apart share an hourly bucket but must split at 5-minute
        # resolution — this is what isolates a cold-revival spike from surrounding traffic.
        self._create_generation(cost=1.0, trace_id="a", timestamp=datetime(2026, 6, 15, 9, 2, tzinfo=UTC))
        self._create_generation(cost=3.0, trace_id="b", timestamp=datetime(2026, 6, 15, 9, 17, tzinfo=UTC))
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=2026-06-15&date_to=2026-06-16&bucket_minutes=5")
        by_bucket = response.json()["by_bucket"]
        assert by_bucket["bucket_minutes"] == 5
        assert [(r["bucket_start"], r["cost_usd"]) for r in by_bucket["items"]] == [
            ("2026-06-15T09:00:00Z", 1.0),
            ("2026-06-15T09:15:00Z", 3.0),
        ]

    def test_by_bucket_defaults_components_to_zero_when_breakdown_missing(self) -> None:
        # Fallback-priced events carry only $ai_total_cost_usd — components must be 0, not an error.
        self._create_generation(cost=1.5, timestamp=datetime(2026, 6, 15, 9, 30, tzinfo=UTC))
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=2026-06-15&date_to=2026-06-16&bucket_minutes=60")
        items = response.json()["by_bucket"]["items"]
        assert len(items) == 1
        assert items[0]["cost_usd"] == 1.5
        assert items[0]["input_cost_usd"] == 0.0
        assert items[0]["cache_creation_cost_usd"] == 0.0
        assert items[0]["cache_read_input_tokens"] == 0

    def test_cache_key_includes_bucket_minutes(self) -> None:
        # Without `bucket_minutes` in the cache key, this second call would be served
        # the cached bucketless payload and silently drop `by_bucket`. The window must
        # stay under the 600-bucket cap, so pin it to a day rather than the 30d default.
        with patch("products.ai_observability.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=-1d")
            response = self.client.get(f"{ENDPOINT}?{PRODUCT_QS}&date_from=-1d&bucket_minutes=60")
        assert response.status_code == status.HTTP_200_OK
        assert "by_bucket" in response.json()

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


INTERNAL_ENDPOINT = "/api/llm_analytics/internal/spend/"
CROSS_REGION_SECRET = "test-cross-region-secret"


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _signed_headers(body: bytes, secret: str = CROSS_REGION_SECRET, timestamp: int | None = None) -> dict[str, str]:
    signature, ts = sign_cross_region_spend_request(body, secret, timestamp=timestamp)
    return {CROSS_REGION_SIGNATURE_HEADER: signature, CROSS_REGION_TIMESTAMP_HEADER: ts}


class TestPersonalSpendInternalEndpoint(ClickhouseTestMixin, APIBaseTest):
    """The US-side receiver of the EU→US proxy: HMAC-gated, no user auth."""

    def setUp(self) -> None:
        super().setUp()
        overrides = override_settings(
            LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id,
            PERSONAL_SPEND_CROSS_REGION_SECRET=CROSS_REGION_SECRET,
        )
        overrides.enable()
        self.addCleanup(overrides.disable)
        cache.clear()
        # No session — the endpoint must work purely off the signature.
        self.client.logout()
        self.payload = {"email": "someone@example.com", "product": "posthog_code"}
        self.body = _json_body(self.payload)

    def _post(self, body: bytes, headers: dict[str, str] | None = None):
        return self.client.post(
            INTERNAL_ENDPOINT,
            data=body,
            content_type="application/json",
            headers=headers or {},
        )

    def test_unsigned_request_rejected(self) -> None:
        response = self._post(self.body)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_wrong_secret_rejected(self) -> None:
        response = self._post(self.body, _signed_headers(self.body, secret="wrong-secret"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_tampered_body_rejected(self) -> None:
        headers = _signed_headers(self.body)
        tampered = _json_body({**self.payload, "email": "victim@example.com"})
        response = self._post(tampered, headers)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_expired_timestamp_rejected(self) -> None:
        stale_ts = int(time.time()) - 3600
        response = self._post(self.body, _signed_headers(self.body, timestamp=stale_ts))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_invalid_utf8_body_rejected(self) -> None:
        headers = {
            CROSS_REGION_SIGNATURE_HEADER: "irrelevant",
            CROSS_REGION_TIMESTAMP_HEADER: str(int(time.time())),
        }
        response = self._post(b"\xff\xfe\xfa", headers)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unset_secret_disables_endpoint(self) -> None:
        with override_settings(PERSONAL_SPEND_CROSS_REGION_SECRET=""):
            response = self._post(self.body, _signed_headers(self.body))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_missing_email_rejected(self) -> None:
        body = _json_body({"product": "posthog_code"})
        response = self._post(body, _signed_headers(body))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_product_rejected(self) -> None:
        body = _json_body({"email": "someone@example.com", "product": "wibble"})
        response = self._post(body, _signed_headers(body))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_signed_request_computes_spend_for_asserted_email(self) -> None:
        _create_person(distinct_ids=["eu-user"], team=self.team, properties={"email": "someone@example.com"})
        _create_event(
            event="$ai_generation",
            team=self.team,
            distinct_id="eu-user",
            properties={
                "$ai_input_tokens": 100,
                "$ai_output_tokens": 10,
                "$ai_model": "claude-opus-4-8",
                "$ai_trace_id": "trace-eu-1",
                "$ai_total_cost_usd": 2.5,
                "ai_product": "posthog_code",
            },
        )
        flush_persons_and_events()

        response = self._post(self.body, _signed_headers(self.body))
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["summary"]["scoped_cost_usd"] == 2.5
        assert body["summary"]["scoped_event_count"] == 1

    def test_signed_request_other_email_sees_nothing(self) -> None:
        _create_person(distinct_ids=["eu-user"], team=self.team, properties={"email": "someone@example.com"})
        _create_event(
            event="$ai_generation",
            team=self.team,
            distinct_id="eu-user",
            properties={"$ai_total_cost_usd": 2.5, "ai_product": "posthog_code"},
        )
        flush_persons_and_events()

        body = _json_body({"email": "other@example.com", "product": "posthog_code"})
        response = self._post(body, _signed_headers(body))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["summary"]["scoped_cost_usd"] == 0


class TestPersonalSpendEUProxy(APIBaseTest):
    """The EU-side view: authenticates locally, then relays a signed call to US."""

    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _get(self, query: dict | None = None, *, user=None):
        factory = APIRequestFactory()
        request = factory.get("/api/llm_analytics/@me/spend/", data=query or {"product": "posthog_code"})
        if user is not None:
            force_authenticate(request, user=user)
        return PersonalSpendEUProxyViewSet.as_view({"get": "list"})(request)

    def test_unauthenticated_rejected_in_region(self) -> None:
        with override_settings(PERSONAL_SPEND_CROSS_REGION_SECRET=CROSS_REGION_SECRET):
            response = self._get()
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_falls_back_to_redirect_while_secret_unset(self) -> None:
        with override_settings(PERSONAL_SPEND_CROSS_REGION_SECRET=""):
            response = self._get(user=self.user)
        assert response.status_code == status.HTTP_302_FOUND
        assert response["Location"].startswith("https://us.posthog.com/api/llm_analytics/@me/spend/")

    def test_invalid_params_rejected_without_upstream_call(self) -> None:
        with override_settings(PERSONAL_SPEND_CROSS_REGION_SECRET=CROSS_REGION_SECRET):
            with patch("products.ai_observability.backend.api.personal_spend.requests.post") as post:
                response = self._get({"product": "wibble"}, user=self.user)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        post.assert_not_called()

    def test_relays_upstream_success_and_signs_asserted_email(self) -> None:
        upstream_payload = {"summary": {"scoped_cost_usd": 1.25}}
        with override_settings(PERSONAL_SPEND_CROSS_REGION_SECRET=CROSS_REGION_SECRET):
            with patch("products.ai_observability.backend.api.personal_spend.requests.post") as post:
                post.return_value.status_code = status.HTTP_200_OK
                post.return_value.json.return_value = upstream_payload
                response = self._get(user=self.user)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == upstream_payload

        (target_url,) = post.call_args.args
        assert target_url.endswith("/api/llm_analytics/internal/spend/")
        sent_body = post.call_args.kwargs["data"]
        sent = json.loads(sent_body)
        assert sent["email"] == self.user.email
        assert sent["product"] == "posthog_code"
        headers = post.call_args.kwargs["headers"]
        ts = int(headers[CROSS_REGION_TIMESTAMP_HEADER])
        expected_signature, _ = sign_cross_region_spend_request(sent_body, CROSS_REGION_SECRET, timestamp=ts)
        assert headers[CROSS_REGION_SIGNATURE_HEADER] == expected_signature

    def test_repeat_request_served_from_local_cache(self) -> None:
        upstream_payload = {"summary": {"scoped_cost_usd": 1.25}}
        with override_settings(PERSONAL_SPEND_CROSS_REGION_SECRET=CROSS_REGION_SECRET):
            with patch("products.ai_observability.backend.api.personal_spend.requests.post") as post:
                post.return_value.status_code = status.HTTP_200_OK
                post.return_value.json.return_value = upstream_payload
                first = self._get(user=self.user)
                second = self._get(user=self.user)

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert second.data == upstream_payload
        assert post.call_count == 1

    @parameterized.expand(
        [
            ("upstream_throttle", status.HTTP_429_TOO_MANY_REQUESTS, status.HTTP_429_TOO_MANY_REQUESTS),
            ("upstream_validation", status.HTTP_400_BAD_REQUEST, status.HTTP_400_BAD_REQUEST),
            ("upstream_signature_mismatch", status.HTTP_401_UNAUTHORIZED, status.HTTP_502_BAD_GATEWAY),
            ("upstream_server_error", status.HTTP_500_INTERNAL_SERVER_ERROR, status.HTTP_502_BAD_GATEWAY),
        ]
    )
    def test_upstream_error_mapping(self, _label: str, upstream_status: int, expected: int) -> None:
        with override_settings(PERSONAL_SPEND_CROSS_REGION_SECRET=CROSS_REGION_SECRET):
            with patch("products.ai_observability.backend.api.personal_spend.requests.post") as post:
                post.return_value.status_code = upstream_status
                post.return_value.json.return_value = {"detail": "upstream detail"}
                response = self._get(user=self.user)
        assert response.status_code == expected

    def test_transport_failure_maps_to_bad_gateway(self) -> None:
        with override_settings(PERSONAL_SPEND_CROSS_REGION_SECRET=CROSS_REGION_SECRET):
            with patch(
                "products.ai_observability.backend.api.personal_spend.requests.post",
                side_effect=requests.ConnectionError("boom"),
            ):
                response = self._get(user=self.user)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
