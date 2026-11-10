from urllib.parse import urlencode

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.summary import ReadySummary, SummaryItem
from products.ai_observability.backend.logic.traces.summary_store import summary_key, write_summary

from .trace_fixtures import GENERATION, T0, encode_segment

READY_SUMMARY = ReadySummary(
    title="Refund request",
    bullets=(SummaryItem(text="The user asks for a refund.", node_id=GENERATION),),
    notes=(),
    flow="ask → refuse",
    model="gpt-4.1-mini",
    generated_at=T0,
)


class TestTraceSummaryViews(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.start = self.enterContext(
            patch("products.ai_observability.backend.facade.api.start_trace_summary", return_value=None)
        )

    def _url(self, segment: str = encode_segment("trace-1")) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/summary/"

    def _store_ready(self) -> None:
        write_summary(summary_key(self.team, self.user, "trace-1"), READY_SUMMARY)

    @parameterized.expand(
        [
            ("no summary", "none", encode_segment("trace-1"), 404),
            ("a ready summary", "ready", encode_segment("trace-1"), 200),
            ("an organization without approval", "unapproved", encode_segment("trace-1"), 403),
            ("a malformed id", "ready", "A", 400),
        ]
    )
    def test_get_maps_each_outcome(self, _name: str, setup: str, segment: str, expected_status: int) -> None:
        if setup != "none":
            self._store_ready()
        if setup == "unapproved":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save()

        response = self.client.get(self._url(segment))

        assert response.status_code == expected_status
        if expected_status == 200:
            body = response.json()
            assert body["status"] == "ready" and body["content"]["generatedAt"] is not None
            assert body["content"]["bullets"][0]["nodeId"] == GENERATION

    def test_post_returns_202_while_pending_and_200_for_a_ready_summary(self) -> None:
        pending = self.client.post(f"{self._url()}?{urlencode({'timestamp_hint': T0.isoformat()})}", {}, format="json")
        self.start.assert_called_once()
        write_summary(summary_key(self.team, self.user, "trace-1"), READY_SUMMARY)
        ready = self.client.post(self._url(), {}, format="json")

        assert (pending.status_code, pending.json()["status"]) == (202, "pending")
        assert self.start.call_args.args[0].timestamp_hint == T0
        assert (ready.status_code, ready.json()["status"]) == (200, "ready")

    @parameterized.expand(
        [
            ("a read key reads", "llm_analytics:read", "get", 200),
            ("a read key cannot request", "llm_analytics:read", "post", 403),
            ("a write key requests", "llm_analytics:write", "post", 200),
        ]
    )
    def test_scopes(self, _name: str, scope: str, method: str, expected_status: int) -> None:
        self._store_ready()
        key = self.create_personal_api_key_with_scopes([scope])
        self.client.logout()

        send = self.client.get if method == "get" else self.client.post
        response = send(self._url(), headers={"authorization": f"Bearer {key}"})

        assert response.status_code == expected_status

    @patch("posthog.rate_limit.AIObservabilitySummarizationBurstThrottle.rate", new="1/minute")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_only_requests_are_throttled(self, _rate_limit_enabled: object) -> None:
        self._store_ready()

        assert self.client.post(self._url(), {}, format="json").status_code == 200
        assert self.client.post(self._url(), {}, format="json").status_code == 429
        assert self.client.get(self._url()).status_code == 200
