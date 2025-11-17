from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Team
from posthog.tasks.activity_log import broadcast_activity_log_to_organization


class TestBroadcastActivityLogToOrganization(BaseTest):
    def test_broadcasts_to_subscribed_teams(self) -> None:
        team_subscribed_1 = Team.objects.create(
            organization=self.organization,
            name="Subscribed Team 1",
            receive_org_level_activity_logs=True,
        )
        team_subscribed_2 = Team.objects.create(
            organization=self.organization,
            name="Subscribed Team 2",
            receive_org_level_activity_logs=True,
        )
        team_not_subscribed = Team.objects.create(
            organization=self.organization,
            name="Not Subscribed Team",
            receive_org_level_activity_logs=False,
        )

        serialized_data = {
            "id": "test-log-id",
            "activity": "updated",
            "scope": "FeatureFlag",
            "item_id": "123",
        }
        user_data = {
            "id": self.user.id,
            "distinct_id": "test-user",
            "email": "test@example.com",
        }

        with patch("posthog.tasks.activity_log.produce_internal_event") as mock_produce:
            broadcast_activity_log_to_organization(
                organization_id=str(self.organization.id),
                serialized_data=serialized_data,
                user_data=user_data,
            )

            self.assertEqual(mock_produce.call_count, 2)

            call_team_ids = [call.kwargs["team_id"] for call in mock_produce.call_args_list]
            self.assertIn(team_subscribed_1.id, call_team_ids)
            self.assertIn(team_subscribed_2.id, call_team_ids)
            self.assertNotIn(team_not_subscribed.id, call_team_ids)

            for call in mock_produce.call_args_list:
                self.assertEqual(call.kwargs["event"].event, "$activity_log_entry_created")
                self.assertEqual(call.kwargs["event"].properties, serialized_data)
                self.assertEqual(call.kwargs["person"].id, self.user.id)

    def test_handles_no_subscribed_teams(self) -> None:
        Team.objects.create(
            organization=self.organization,
            name="Not Subscribed Team",
            receive_org_level_activity_logs=False,
        )

        serialized_data = {"id": "test-log-id"}
        user_data = {"id": self.user.id, "distinct_id": "test-user"}

        with patch("posthog.tasks.activity_log.produce_internal_event") as mock_produce:
            broadcast_activity_log_to_organization(
                organization_id=str(self.organization.id),
                serialized_data=serialized_data,
                user_data=user_data,
            )

            mock_produce.assert_not_called()
