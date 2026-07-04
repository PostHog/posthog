import json
from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import ANY, MagicMock, patch

from django.conf import settings

from temporalio.service import RPCError

from posthog.models import OrganizationMembership, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import describe_schedule
from posthog.temporal.common.test_utils import start_test_worker
from posthog.temporal.tests.delete_teams.inline import execute_deletion_workflows_inline

from products.batch_exports.backend.temporal import ACTIVITIES, WORKFLOWS
from products.early_access_features.backend.models import EarlyAccessFeature


class TestTeamDeletionSideEffects(NonAtomicBaseTest):
    """Deletion side-effect coverage, exercised by running the Temporal deletion workflow inline.

    These tests assert on the actual effects of team deletion (records removed, batch exports and
    schedules torn down, persons cleaned up). They run the durable Temporal workflow to completion
    via ``execute_deletion_workflows_inline`` and therefore require a non-atomic test case so the
    workflow's activities (which run on their own connections) can see committed test data.
    """

    # Recreate org/team/user per test: TransactionTestCase flushes the DB between tests, which would
    # otherwise leave class-level fixture data dangling.
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.force_login(self.user)

    @freeze_time("2022-02-08")
    def test_delete_team_activity_log(self):
        team: Team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)

        with execute_deletion_workflows_inline():
            response = self.client.delete(f"/api/environments/{team.id}")
        assert response.status_code == 204

        # The team was deleted, so its activity can no longer be viewed via the API even though it was recorded
        deleted_team_activity_response = self.client.get(f"/api/environments/{team.id}/activity")
        assert deleted_team_activity_response.status_code == 404

        # We can't query by API but can prove the deletion was recorded in the activity log
        activity = [a.__dict__ for a in ActivityLog.objects.filter(team_id=team.pk).order_by("scope").all()]
        assert activity == [
            {
                "_state": ANY,
                "id": ANY,
                "team_id": team.pk,
                "organization_id": ANY,
                "user_id": None,
                "was_impersonated": False,
                "is_system": True,
                "activity": "created",
                "item_id": ANY,
                "scope": "Dashboard",
                "detail": {
                    "name": "Your starter dashboard",
                    "type": "dashboard",
                    "changes": [],
                    "context": None,
                    "short_id": None,
                    "trigger": None,
                },
                "client": None,
                "created_at": ANY,
                "ip_address": None,
            },
            {
                "_state": ANY,
                "activity": "deleted",
                "created_at": ANY,
                "detail": {
                    "changes": None,
                    "context": None,
                    "name": "Default project",
                    "short_id": None,
                    "trigger": None,
                    "type": None,
                },
                "id": ANY,
                "is_system": False,
                "organization_id": ANY,
                "team_id": team.pk,
                "item_id": str(team.pk),
                "scope": "Team",
                "user_id": self.user.pk,
                "was_impersonated": False,
                "client": None,
                "ip_address": "127.0.0.1",
            },
        ]

    def test_delete_bulky_postgres_data(self):
        from posthog.personhog_client.fake_client import get_active_fake
        from posthog.test.persons import add_cohort_members, add_distinct_id, create_person

        from products.cohorts.backend.models.cohort import Cohort
        from products.feature_flags.backend.models.feature_flag import FeatureFlag

        team: Team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 2)

        cohort = Cohort.objects.create(team=team, created_by=self.user, name="test")
        person = create_person(
            team=team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )
        add_distinct_id(person=person, distinct_id="test")
        flag = FeatureFlag.objects.create(team=team, name="test", key="test", created_by=self.user)
        add_cohort_members(cohort, [person])
        EarlyAccessFeature.objects.create(
            team=team, name="Test flag", description="A fancy new flag.", stage="beta", feature_flag=flag
        )

        with execute_deletion_workflows_inline():
            response = self.client.delete(f"/api/environments/{team.id}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Team.objects.filter(id=team.id).exists())

        # Verify personhog RPCs were called for persons-DB cleanup
        fake = get_active_fake()
        for rpc in [
            "delete_hash_key_overrides_by_teams",
            "delete_personless_distinct_ids_batch_for_team",
            "delete_persons_batch_for_team",
            "delete_groups_batch_for_team",
            "delete_group_type_mappings_batch_for_team",
        ]:
            fake.assert_called(rpc)

    def test_delete_batch_exports(self):
        team: Team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)

        batch_export_data = {
            "name": "my-production-s3-bucket-destination",
            "destination": {
                "type": "AwsS3",
                "config": {
                    "bucket_name": "my-production-s3-bucket",
                    "region": "us-east-1",
                    "prefix": "posthog-events/",
                    "aws_access_key_id": "abc123",
                    "aws_secret_access_key": "secret",
                },
            },
            "interval": "hour",
        }

        temporal = sync_connect()

        with start_test_worker(
            temporal,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
        ):
            response = self.client.post(
                f"/api/environments/{team.id}/batch_exports",
                json.dumps(batch_export_data),
                content_type="application/json",
            )
            assert response.status_code == 201, response.json()
            batch_export_id = response.json()["id"]

            with execute_deletion_workflows_inline():
                response = self.client.delete(f"/api/environments/{team.id}")
            assert response.status_code == 204, response.json()

            response = self.client.get(f"/api/environments/{team.id}/batch_exports/{batch_export_id}")
            assert response.status_code == 404, response.json()

            with self.assertRaises(RPCError):
                describe_schedule(temporal, batch_export_id)

    def test_delete_team_with_already_deleted_batch_export(self):
        """Team deletion should succeed even if batch exports were already soft-deleted."""
        team: Team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)

        batch_export_data = {
            "name": "my-production-s3-bucket-destination",
            "destination": {
                "type": "AwsS3",
                "config": {
                    "bucket_name": "my-production-s3-bucket",
                    "region": "us-east-1",
                    "prefix": "posthog-events/",
                    "aws_access_key_id": "abc123",
                    "aws_secret_access_key": "secret",
                },
            },
            "interval": "hour",
        }

        temporal = sync_connect()

        with start_test_worker(
            temporal,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
        ):
            response = self.client.post(
                f"/api/environments/{team.id}/batch_exports",
                json.dumps(batch_export_data),
                content_type="application/json",
            )
            assert response.status_code == 201, response.json()
            batch_export_id = response.json()["id"]

            # Delete the batch export first (this soft-deletes it and removes the Temporal schedule)
            response = self.client.delete(f"/api/environments/{team.id}/batch_exports/{batch_export_id}")
            assert response.status_code == 204

            with self.assertRaises(RPCError):
                describe_schedule(temporal, batch_export_id)

            # Now delete the team - this should succeed
            with execute_deletion_workflows_inline():
                response = self.client.delete(f"/api/environments/{team.id}")
            assert response.status_code == 204

    @patch("posthog.temporal.common.schedule.delete_schedule")
    @patch("posthog.models.team.util.sync_connect")
    def test_delete_data_modeling_schedules(self, mock_sync_connect, mock_delete_schedule):
        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

        team: Team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=team,
            name="test_scheduled_query",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            sync_frequency_interval=timedelta(hours=1),
        )

        mock_temporal = MagicMock()
        mock_sync_connect.return_value = mock_temporal

        with execute_deletion_workflows_inline():
            response = self.client.delete(f"/api/environments/{team.id}")
        assert response.status_code == 204

        mock_delete_schedule.assert_called_once_with(mock_temporal, schedule_id=str(saved_query.id))

    @patch("posthog.temporal.common.schedule.delete_schedule")
    @patch("posthog.models.team.util.sync_connect")
    def test_delete_data_modeling_schedules_handles_not_found(self, mock_sync_connect, mock_delete_schedule):
        import temporalio.service

        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

        team: Team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)

        DataWarehouseSavedQuery.objects.create(
            team=team,
            name="test_missing_schedule",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            sync_frequency_interval=timedelta(hours=1),
        )

        mock_temporal = MagicMock()
        mock_sync_connect.return_value = mock_temporal
        mock_delete_schedule.side_effect = temporalio.service.RPCError(
            "not found", temporalio.service.RPCStatusCode.NOT_FOUND, b""
        )

        with execute_deletion_workflows_inline():
            response = self.client.delete(f"/api/environments/{team.id}")
        assert response.status_code == 204
