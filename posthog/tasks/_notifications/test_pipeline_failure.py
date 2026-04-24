from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import OrganizationMembership
from posthog.tasks._notifications.pipeline_failure import dispatch_pipeline_failure_realtime


class TestDispatchPipelineFailureRealtime(BaseTest):
    @patch("posthog.tasks._notifications.pipeline_failure.create_notification")
    def test_dispatches_one_notification_per_membership(self, mock_create_notification):
        user2 = self._create_user("subscriber@test.com")
        memberships = list(
            OrganizationMembership.objects.filter(organization=self.organization, user__in=[self.user, user2])
        )

        dispatch_pipeline_failure_realtime(
            team=self.team,
            memberships=memberships,
            title="Plugin foo disabled",
            body="boom",
            resource_id="42",
            source_url="/project/1/pipeline/transformations/42",
        )

        assert mock_create_notification.call_count == 2
        targets = sorted(call.args[0].target_id for call in mock_create_notification.call_args_list)
        assert targets == sorted([str(self.user.id), str(user2.id)])

    @patch("posthog.tasks._notifications.pipeline_failure.create_notification", side_effect=RuntimeError("kafka"))
    def test_swallows_exceptions(self, _mock_create):
        memberships = list(OrganizationMembership.objects.filter(user=self.user, organization=self.organization))
        dispatch_pipeline_failure_realtime(
            team=self.team,
            memberships=memberships,
            title="x",
            body="y",
            resource_id="1",
            source_url="/",
        )
