import base64
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.models.review_queues import ReviewQueue

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _create_trace(team: Team, trace_id: str = "trace-1") -> None:
    bulk_create_ai_events(
        [
            {
                "event": "$ai_generation",
                "event_uuid": "00000000-0000-0000-0000-000000000001",
                "distinct_id": "user-1",
                "team": team,
                "timestamp": T0,
                "properties": {"$ai_trace_id": trace_id, "$ai_parent_id": trace_id, "$ai_input_tokens": 3},
            }
        ]
    )


def _encode(trace_id: str) -> str:
    return base64.urlsafe_b64encode(trace_id.encode()).decode().rstrip("=")


class TestTraceViewSet(ClickhouseTestMixin, APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/"

    @parameterized.expand([("plain id", "trace-1"), ("id with a dot", "run.42"), ("id with a slash", "a/b")])
    def test_returns_the_trace_in_camel_case(self, _name: str, trace_id: str) -> None:
        _create_trace(self.team, trace_id)

        response = self.client.get(self._url(_encode(trace_id)))

        assert response.status_code == 200
        body = response.json()
        assert body["tree"][0]["id"] == trace_id
        assert body["tree"][0]["children"][0]["id"] == "00000000-0000-0000-0000-000000000001"
        assert body["totals"]["inputTokens"] == 3
        assert body["threadNodeIds"] == ["00000000-0000-0000-0000-000000000001"]

    @parameterized.expand([("unknown trace", False), ("another team's trace", True)])
    def test_not_found(self, _name: str, other_team_owns_it: bool) -> None:
        if other_team_owns_it:
            _create_trace(Team.objects.create(organization=self.organization, name="other"), "trace-2")

        assert self.client.get(self._url(_encode("trace-2"))).status_code == 404

    @parameterized.expand(
        [
            ("malformed timestamp hint", _encode("trace-1"), {"timestamp_hint": "yesterday"}),
            ("timestamp hint at the end of time", _encode("trace-1"), {"timestamp_hint": "9999-12-31T23:59:59Z"}),
            ("timestamp hint at the start of time", _encode("trace-1"), {"timestamp_hint": "0001-01-01T00:00:00Z"}),
            ("unencoded trace id", "trace-1", {}),
        ]
    )
    def test_rejects_a_malformed_request(self, _name: str, segment: str, query: dict[str, str]) -> None:
        _create_trace(self.team, "trace-1")

        assert self.client.get(self._url(segment), query).status_code == 400

    @parameterized.expand([("browser session", False, "app_per_org"), ("personal api key", True, "api_per_team")])
    def test_throttles_when_the_query_concurrency_limit_is_exhausted(
        self, _name: str, with_api_key: bool, exhausted_limit: str
    ) -> None:
        _create_trace(self.team, "trace-1")
        headers = {}
        if with_api_key:
            headers["authorization"] = f"Bearer {self.create_personal_api_key_with_scopes(['llm_analytics:read'])}"
            self.client.logout()

        def use(limiter: RateLimit, *args: object, **kwargs: object) -> ConcurrencySlot | None:
            if limiter.limit_name == exhausted_limit:
                raise ConcurrencyLimitExceeded(exhausted_limit)
            return None

        with (
            patch("posthog.clickhouse.client.limit.TEST", False),
            patch.object(RateLimit, "use", autospec=True, side_effect=use),
        ):
            response = self.client.get(self._url(_encode("trace-1")), headers=headers)

        assert response.status_code == 429


class TestTraceViewSetResourceLevelAccess(ClickhouseTestMixin, APIBaseTest):
    def test_a_grant_on_one_object_does_not_open_traces(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        queue = ReviewQueue.objects.create(team=self.team, name="Support queue", created_by=self.user)
        member = User.objects.create_and_join(self.organization, "queue-reviewer@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", access_level="none", organization_member=membership
        )
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=str(queue.id),
            access_level="viewer",
            organization_member=membership,
        )
        _create_trace(self.team)
        self.client.force_login(member)

        response = self.client.get(f"/api/projects/{self.team.id}/ai_observability/traces/{_encode('trace-1')}/")

        assert response.status_code == 403, response.content
