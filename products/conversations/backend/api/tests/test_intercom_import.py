from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.db import IntegrityError, transaction

from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.utils import generate_random_token_secret

from products.conversations.backend.models import EmailChannel, EmailChannelKind, IntercomImportJob

URL = "/api/projects/{team_id}/conversations/intercom_imports/"
M = "products.conversations.backend.api.intercom_import"


@patch(f"{M}.posthoganalytics.feature_enabled", return_value=True)
@patch(
    f"{M}.start_intercom_import_workflow",
    new_callable=AsyncMock,
    return_value=("workflow-id", "run-id"),
)
@patch(f"{M}.validate_intercom_credentials", return_value=True)
class TestIntercomImportAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = URL.format(team_id=self.team.id)

    def test_start_import_stores_token_but_never_returns_it(self, _mock_validate, mock_start, _mock_flag):
        token = generate_random_token_secret()

        response = self.client.post(self.url, {"region": "eu", "access_token": token}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual((body["status"], body["region"], body["has_credentials"]), ("running", "eu", True))
        self.assertNotIn(token, response.content.decode())
        job = IntercomImportJob.objects.unscoped().get(team_id=self.team.id)
        self.assertEqual(job.job_inputs, {"region": "eu", "access_token": token})
        self.assertEqual(mock_start.call_args.kwargs["job_id"], str(job.id))

        status_response = self.client.get(f"{self.url}status/")
        self.assertEqual(status_response.json()["id"], str(job.id))
        self.assertNotIn(token, status_response.content.decode())

    def test_rejected_token_creates_no_job(self, mock_validate, mock_start, _mock_flag):
        mock_validate.return_value = False

        response = self.client.post(self.url, {"access_token": generate_random_token_secret()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(IntercomImportJob.objects.unscoped().filter(team_id=self.team.id).exists())
        mock_start.assert_not_called()

    def test_rejects_duplicate_running_job(self, _mock_validate, mock_start, _mock_flag):
        IntercomImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=IntercomImportJob.Status.RUNNING,
            job_inputs={"region": "us", "access_token": "x"},
        )

        response = self.client.post(self.url, {"access_token": generate_random_token_secret()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_start.assert_not_called()

    def test_customer_communication_channel_cannot_be_the_import_channel(self, _mock_validate, mock_start, _mock_flag):
        customer_channel = EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
            owner=self.user,
            inbound_token="customer-intercom-token",
            from_email="csm@example.com",
            from_name="Customer success",
            domain="example.com",
        )

        response = self.client.post(
            self.url,
            {"access_token": generate_random_token_secret(), "default_email_channel_id": str(customer_channel.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_start.assert_not_called()

    def test_non_admin_member_cannot_start_or_poll(self, _mock_validate, mock_start, _mock_flag):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        post = self.client.post(self.url, {"access_token": generate_random_token_secret()}, format="json")
        get = self.client.get(f"{self.url}status/")

        self.assertEqual((post.status_code, get.status_code), (status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN))
        mock_start.assert_not_called()

    def test_status_returns_404_when_no_job(self, _mock_validate, _mock_start, _mock_flag):
        response = self.client.get(f"{self.url}status/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_flag_off_blocks_start_and_status_without_probing_intercom(self, mock_validate, mock_start, mock_flag):
        mock_flag.return_value = False

        post = self.client.post(self.url, {"access_token": generate_random_token_secret()}, format="json")
        get = self.client.get(f"{self.url}status/")

        self.assertEqual((post.status_code, get.status_code), (status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN))
        mock_validate.assert_not_called()
        mock_start.assert_not_called()

    def test_active_job_constraint_rejects_a_second_pending_job(self, _mock_validate, mock_start, _mock_flag):
        # A concurrent request can pass the exists() fast path before the first job is saved; the
        # partial unique index is what stops it, so exercise the index directly.
        IntercomImportJob.objects.unscoped().create(
            team_id=self.team.id, status=IntercomImportJob.Status.PENDING, job_inputs={"region": "us"}
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            IntercomImportJob.objects.unscoped().create(
                team_id=self.team.id, status=IntercomImportJob.Status.RUNNING, job_inputs={"region": "us"}
            )
        # A finished job doesn't count, so the next import can start.
        IntercomImportJob.objects.unscoped().create(
            team_id=self.team.id, status=IntercomImportJob.Status.COMPLETED, job_inputs={"region": "us"}
        )

    def test_start_does_not_overwrite_a_job_the_workflow_already_finished(
        self, _mock_validate, _mock_start, _mock_flag
    ):
        async def started():
            return ("workflow-id", "run-id")

        def finish_before_the_view_saves(*, job_id: str, **_kwargs):
            # Runs while the view builds the coroutine, before asyncio.run, so the ORM write is allowed.
            IntercomImportJob.objects.unscoped().filter(id=job_id).update(status=IntercomImportJob.Status.COMPLETED)
            return started()

        with patch(f"{M}.start_intercom_import_workflow", new=finish_before_the_view_saves):
            response = self.client.post(self.url, {"access_token": generate_random_token_secret()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], "completed")
        job = IntercomImportJob.objects.unscoped().get(team_id=self.team.id)
        self.assertEqual((job.status, job.workflow_id), (IntercomImportJob.Status.COMPLETED, "workflow-id"))
