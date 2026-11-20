from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.db import IntegrityError, transaction
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.utils import generate_random_token_secret

from products.conversations.backend.api.pylon_import import ORPHANED_PENDING_AFTER, QUIET_RUNNING_AFTER
from products.conversations.backend.models import EmailChannel, EmailChannelKind, PylonImportJob
from products.conversations.backend.temporal.pylon_import.client import PylonCredentials

URL = "/api/projects/{team_id}/conversations/pylon_imports/"
M = "products.conversations.backend.api.pylon_import"


@patch(f"{M}.posthoganalytics.feature_enabled", return_value=True)
@patch(
    f"{M}.start_pylon_import_workflow",
    new_callable=AsyncMock,
    return_value=("workflow-id", "run-id"),
)
@patch(f"{M}.resolve_pylon_credentials", side_effect=lambda token: PylonCredentials(region="eu", api_token=token))
class TestPylonImportAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = URL.format(team_id=self.team.id)

    def test_start_import_stores_token_but_never_returns_it(self, _mock_validate, mock_start, _mock_flag):
        token = generate_random_token_secret()

        response = self.client.post(self.url, {"api_token": token}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual((body["status"], body["region"], body["has_credentials"]), ("running", "eu", True))
        self.assertNotIn(token, response.content.decode())
        job = PylonImportJob.objects.unscoped().get(team_id=self.team.id)
        # The region is the one Pylon accepted the token in, not a user input.
        self.assertEqual(job.job_inputs, {"region": "eu", "api_token": token})
        self.assertEqual(mock_start.call_args.kwargs["job_id"], str(job.id))

        status_response = self.client.get(f"{self.url}status/")
        self.assertEqual(status_response.json()["id"], str(job.id))
        self.assertNotIn(token, status_response.content.decode())

    def test_rejected_token_creates_no_job(self, mock_validate, mock_start, _mock_flag):
        mock_validate.side_effect = None
        mock_validate.return_value = None

        response = self.client.post(self.url, {"api_token": generate_random_token_secret()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PylonImportJob.objects.unscoped().filter(team_id=self.team.id).exists())
        mock_start.assert_not_called()

    def test_rejects_duplicate_running_job(self, _mock_validate, mock_start, _mock_flag):
        PylonImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=PylonImportJob.Status.RUNNING,
            job_inputs={"region": "us", "api_token": "x"},
        )

        response = self.client.post(self.url, {"api_token": generate_random_token_secret()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_start.assert_not_called()

    def test_customer_communication_channel_cannot_be_the_import_channel(self, _mock_validate, mock_start, _mock_flag):
        customer_channel = EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
            owner=self.user,
            inbound_token="customer-pylon-token",
            from_email="csm@example.com",
            from_name="Customer success",
            domain="example.com",
        )

        response = self.client.post(
            self.url,
            {"api_token": generate_random_token_secret(), "default_email_channel_id": str(customer_channel.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_start.assert_not_called()

    def test_non_admin_member_cannot_start_or_poll(self, _mock_validate, mock_start, _mock_flag):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        post = self.client.post(self.url, {"api_token": generate_random_token_secret()}, format="json")
        get = self.client.get(f"{self.url}status/")

        self.assertEqual((post.status_code, get.status_code), (status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN))
        mock_start.assert_not_called()

    def test_status_returns_404_when_no_job(self, _mock_validate, _mock_start, _mock_flag):
        response = self.client.get(f"{self.url}status/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_flag_off_blocks_start_and_status_without_probing_pylon(self, mock_validate, mock_start, mock_flag):
        mock_flag.return_value = False

        post = self.client.post(self.url, {"api_token": generate_random_token_secret()}, format="json")
        get = self.client.get(f"{self.url}status/")

        self.assertEqual((post.status_code, get.status_code), (status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN))
        mock_validate.assert_not_called()
        mock_start.assert_not_called()

    def test_active_job_constraint_rejects_a_second_pending_job(self, _mock_validate, mock_start, _mock_flag):
        # A concurrent request can pass the exists() fast path before the first job is saved; the
        # partial unique index is what stops it, so exercise the index directly.
        PylonImportJob.objects.unscoped().create(
            team_id=self.team.id, status=PylonImportJob.Status.PENDING, job_inputs={"region": "us"}
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PylonImportJob.objects.unscoped().create(
                team_id=self.team.id, status=PylonImportJob.Status.RUNNING, job_inputs={"region": "us"}
            )
        # A finished job doesn't count, so the next import can start.
        PylonImportJob.objects.unscoped().create(
            team_id=self.team.id, status=PylonImportJob.Status.COMPLETED, job_inputs={"region": "us"}
        )

    def test_start_does_not_overwrite_a_job_the_workflow_already_finished(
        self, _mock_validate, _mock_start, _mock_flag
    ):
        async def started():
            return ("workflow-id", "run-id")

        def finish_before_the_view_saves(*, job_id: str, **_kwargs):
            # Runs while the view builds the coroutine, before asyncio.run, so the ORM write is allowed.
            PylonImportJob.objects.unscoped().filter(id=job_id).update(status=PylonImportJob.Status.COMPLETED)
            return started()

        with patch(f"{M}.start_pylon_import_workflow", new=finish_before_the_view_saves):
            response = self.client.post(self.url, {"api_token": generate_random_token_secret()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], "completed")
        job = PylonImportJob.objects.unscoped().get(team_id=self.team.id)
        self.assertEqual((job.status, job.workflow_id), (PylonImportJob.Status.COMPLETED, "workflow-id"))

    def _stale_pending_job(self) -> PylonImportJob:
        job = PylonImportJob.objects.unscoped().create(
            team_id=self.team.id, status=PylonImportJob.Status.PENDING, job_inputs={"region": "us"}
        )
        PylonImportJob.objects.unscoped().filter(id=job.id).update(
            created_at=timezone.now() - ORPHANED_PENDING_AFTER - timedelta(minutes=1)
        )
        return job

    @patch(f"{M}.pylon_import_workflow_exists", new_callable=AsyncMock, return_value=False)
    def test_orphaned_pending_reservation_is_released(self, _mock_exists, _mock_validate, mock_start, _mock_flag):
        self._stale_pending_job()

        status_response = self.client.get(f"{self.url}status/")
        response = self.client.post(self.url, {"api_token": generate_random_token_secret()}, format="json")

        self.assertEqual(status_response.json()["status"], "failed")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_start.assert_called_once()

    @patch(f"{M}.pylon_import_workflow_exists", new_callable=AsyncMock, return_value=True)
    def test_stale_reservation_with_a_live_workflow_is_kept(self, _mock_exists, _mock_validate, mock_start, _mock_flag):
        # The web process died after Temporal accepted the workflow but before saving workflow_id.
        job = self._stale_pending_job()

        response = self.client.post(self.url, {"api_token": generate_random_token_secret()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        job.refresh_from_db()
        self.assertEqual(job.status, PylonImportJob.Status.PENDING)
        mock_start.assert_not_called()

    @parameterized.expand([("workflow_exists", True, "pending"), ("workflow_missing", False, "failed")])
    def test_failed_start_keeps_the_reservation_unless_temporal_confirms_no_workflow(
        self, _mock_validate, mock_start, _mock_flag, _name, workflow_exists, expected_status
    ):
        mock_start.side_effect = TimeoutError("deadline exceeded")

        with patch(f"{M}.pylon_import_workflow_exists", new_callable=AsyncMock, return_value=workflow_exists):
            response = self.client.post(self.url, {"api_token": generate_random_token_secret()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(PylonImportJob.objects.unscoped().get(team_id=self.team.id).status, expected_status)

    @parameterized.expand([("workflow_stopped", False, "failed"), ("workflow_running", True, "running")])
    def test_quiet_running_job_is_failed_only_when_its_workflow_stopped(
        self, _mock_validate, _mock_start, _mock_flag, _name, workflow_running, expected_status
    ):
        job = PylonImportJob.objects.unscoped().create(
            team_id=self.team.id, status=PylonImportJob.Status.RUNNING, job_inputs={"region": "us"}
        )
        PylonImportJob.objects.unscoped().filter(id=job.id).update(
            updated_at=timezone.now() - QUIET_RUNNING_AFTER - timedelta(minutes=1)
        )

        with patch(
            f"{M}.pylon_import_workflow_is_running", new_callable=AsyncMock, return_value=workflow_running
        ) as is_running:
            first = self.client.get(f"{self.url}status/")
            self.client.get(f"{self.url}status/")

        self.assertEqual(first.json()["status"], expected_status)
        is_running.assert_called_once()

    def test_recent_pending_reservation_still_blocks_a_second_import(self, _mock_validate, mock_start, _mock_flag):
        PylonImportJob.objects.unscoped().create(
            team_id=self.team.id, status=PylonImportJob.Status.PENDING, job_inputs={"region": "us"}
        )

        response = self.client.post(self.url, {"api_token": generate_random_token_secret()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_start.assert_not_called()
