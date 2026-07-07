import uuid
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.admin.admins.external_data_job_admin import ExternalDataJobAdmin

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


def _fake_reverse(name, args=None, kwargs=None):
    if args:
        return f"/{name}/{'/'.join(str(a) for a in args)}/"
    return f"/{name}/"


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestExternalDataJobAdminMarkFailed(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = ExternalDataJobAdmin(ExternalDataJob, AdminSite())

    def _create_job(self, status: str = ExternalDataJob.Status.RUNNING) -> ExternalDataJob:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        schema = ExternalDataSchema.objects.create(
            name="invoices",
            team_id=self.team.pk,
            source=source,
        )
        return ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline=source,
            schema=schema,
            status=status,
            rows_synced=42,
            workflow_id="wf-123",
            workflow_run_id="wfr-123",
        )

    def _call_mark_failed(self, method: str, job: ExternalDataJob, data: dict | None = None):
        path = f"/admin/data_warehouse/externaldatajob/{job.pk}/mark-failed/"
        if method == "GET":
            http_request = self.factory.get(path)
        else:
            http_request = self.factory.post(path, data or {})
        http_request.user = self.user
        _attach_messages(http_request)
        with patch("posthog.admin.admins.external_data_job_admin.reverse", side_effect=_fake_reverse):
            return self.admin.mark_failed_view(http_request, str(job.pk))

    def test_post_flips_running_job_to_failed(self):
        job = self._create_job(status=ExternalDataJob.Status.RUNNING)

        response = self._call_mark_failed("POST", job, {"reason": "workflow terminated in Temporal"})

        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, ExternalDataJob.Status.FAILED)
        self.assertEqual(job.latest_error, "workflow terminated in Temporal")
        self.assertIsNotNone(job.finished_at)

    def test_post_without_reason_uses_default_error_message(self):
        job = self._create_job(status=ExternalDataJob.Status.RUNNING)

        response = self._call_mark_failed("POST", job, {})

        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, ExternalDataJob.Status.FAILED)
        assert job.latest_error is not None
        self.assertIn("Marked Failed via admin", job.latest_error)

    def test_get_does_not_change_status(self):
        job = self._create_job(status=ExternalDataJob.Status.RUNNING)

        response = self._call_mark_failed("GET", job)

        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, ExternalDataJob.Status.RUNNING)

    @parameterized.expand(
        [
            ("completed", ExternalDataJob.Status.COMPLETED),
            ("failed", ExternalDataJob.Status.FAILED),
            ("billing_limit_reached", ExternalDataJob.Status.BILLING_LIMIT_REACHED),
            ("billing_limit_too_low", ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW),
        ]
    )
    def test_post_noop_when_status_is_not_running(self, _name, status):
        job = self._create_job(status=status)
        original_error = job.latest_error
        original_finished_at = job.finished_at

        response = self._call_mark_failed("POST", job, {"reason": "should not apply"})

        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, status)
        self.assertEqual(job.latest_error, original_error)
        self.assertEqual(job.finished_at, original_finished_at)

    def test_post_preserves_existing_finished_at(self):
        existing_finished_at = timezone.now() - timedelta(hours=1)
        job = self._create_job(status=ExternalDataJob.Status.RUNNING)
        ExternalDataJob.objects.filter(pk=job.pk).update(finished_at=existing_finished_at)

        self._call_mark_failed("POST", job, {"reason": "x"})

        job.refresh_from_db()
        self.assertEqual(job.finished_at, existing_finished_at)


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestExternalDataJobAdminChangeView(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = ExternalDataJobAdmin(ExternalDataJob, AdminSite())

    def _create_job(self, status: str, workflow_id: str | None = "wf-123") -> ExternalDataJob:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
        )
        schema = ExternalDataSchema.objects.create(
            name="customers",
            team_id=self.team.pk,
            source=source,
        )
        return ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline=source,
            schema=schema,
            status=status,
            workflow_id=workflow_id,
            workflow_run_id="wfr-456" if workflow_id else None,
        )

    def _change_view_context(self, job: ExternalDataJob) -> dict:
        http_request = self.factory.get(f"/admin/data_warehouse/externaldatajob/{job.pk}/change/")
        http_request.user = self.user
        _attach_messages(http_request)
        captured: dict = {}

        def _capture_super(self_admin, http_req, object_id, form_url, extra_context):
            captured.update(extra_context)
            from django.http import HttpResponse

            return HttpResponse(status=200)

        with (
            patch("posthog.admin.admins.external_data_job_admin.reverse", side_effect=_fake_reverse),
            patch("django.contrib.admin.ModelAdmin.change_view", _capture_super),
        ):
            self.admin.change_view(http_request, str(job.pk))
        return captured

    def test_change_view_marks_is_running_true_for_running_job(self):
        job = self._create_job(status=ExternalDataJob.Status.RUNNING)
        context = self._change_view_context(job)
        self.assertTrue(context["is_running"])
        self.assertIn("mark_failed_url", context)
        self.assertIn("schema_admin_url", context)

    @parameterized.expand(
        [
            ("completed", ExternalDataJob.Status.COMPLETED),
            ("failed", ExternalDataJob.Status.FAILED),
            ("billing_limit_reached", ExternalDataJob.Status.BILLING_LIMIT_REACHED),
        ]
    )
    def test_change_view_marks_is_running_false_for_non_running_job(self, _name, status):
        job = self._create_job(status=status)
        context = self._change_view_context(job)
        self.assertFalse(context["is_running"])

    def test_change_view_omits_schema_admin_url_when_no_schema(self):
        job = self._create_job(status=ExternalDataJob.Status.RUNNING)
        ExternalDataJob.objects.filter(pk=job.pk).update(schema=None)
        job.refresh_from_db()

        context = self._change_view_context(job)
        self.assertNotIn("schema_admin_url", context)


@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    TEMPORAL_UI_HOST="https://temporal.example.com",
    TEMPORAL_NAMESPACE="ph-test",
    SITE_URL="https://app.posthog.example",
)
class TestExternalDataJobAdminDisplayMethods(BaseTest):
    def setUp(self):
        super().setUp()
        self.admin = ExternalDataJobAdmin(ExternalDataJob, AdminSite())

    def _create_job(self, **kwargs) -> ExternalDataJob:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
        )
        schema = ExternalDataSchema.objects.create(
            name="charges",
            team_id=self.team.pk,
            source=source,
        )
        defaults = {
            "team_id": self.team.pk,
            "pipeline": source,
            "schema": schema,
            "status": ExternalDataJob.Status.RUNNING,
            "workflow_id": "wf-abc",
            "workflow_run_id": "wfr-abc",
        }
        defaults.update(kwargs)
        return ExternalDataJob.objects.create(**defaults)

    def test_temporal_workflow_link_renders_url_when_ids_present(self):
        job = self._create_job()
        html = str(self.admin.temporal_workflow_link(job))
        self.assertIn("https://temporal.example.com/namespaces/ph-test/workflows/wf-abc/wfr-abc", html)
        self.assertIn("View workflow", html)

    def test_temporal_workflow_link_dash_when_workflow_id_missing(self):
        job = self._create_job(workflow_id=None, workflow_run_id=None)
        self.assertEqual(self.admin.temporal_workflow_link(job), "—")

    def test_temporal_workflow_link_dash_when_run_id_missing(self):
        job = self._create_job(workflow_run_id=None)
        self.assertEqual(self.admin.temporal_workflow_link(job), "—")

    def test_logs_link_renders_url_when_workflow_id_present(self):
        job = self._create_job()
        html = str(self.admin.logs_link(job))
        self.assertIn(f"https://app.posthog.example/project/{self.team.pk}/logs?searchTerm=wf-abc", html)
        self.assertIn("View logs", html)

    def test_logs_link_dash_when_workflow_id_missing(self):
        job = self._create_job(workflow_id=None)
        self.assertEqual(self.admin.logs_link(job), "—")

    def test_source_type_returns_pipeline_type(self):
        job = self._create_job()
        self.assertEqual(self.admin.source_type(job), "Stripe")
