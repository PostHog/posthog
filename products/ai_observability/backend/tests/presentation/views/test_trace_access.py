from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.models.review_queues import ReviewQueue

from .trace_fixtures import create_trace, encode_segment

TRACE = encode_segment("trace-1")


class TestTraceViewSetResourceLevelAccess(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("the list", "get", ""),
            ("the list's previews", "post", "previews/"),
            ("the trace", "get", f"{TRACE}/"),
            ("a node", "get", f"{TRACE}/nodes/{TRACE}/"),
            ("its evaluations", "get", f"{TRACE}/evaluations/"),
            ("its clusters", "get", f"{TRACE}/clusters/"),
            ("its feedback", "get", f"{TRACE}/feedback/"),
            ("its review", "get", f"{TRACE}/review/"),
            ("a search", "get", f"{TRACE}/search/"),
            ("its summary", "get", f"{TRACE}/summary/"),
            ("an export", "post", f"{TRACE}/exports/"),
        ]
    )
    def test_a_grant_on_one_object_does_not_open_traces(self, _name: str, method: str, path: str) -> None:
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
        create_trace(self.team)
        self.client.force_login(member)

        url = f"/api/projects/{self.team.id}/ai_observability/traces/{path}"
        response = getattr(self.client, method)(url)

        assert response.status_code == 403, response.content
