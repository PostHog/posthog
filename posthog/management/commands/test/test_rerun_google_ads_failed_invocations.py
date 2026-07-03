from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

RERUN_HELPER = "posthog.management.commands.rerun_google_ads_failed_invocations.rerun_hog_invocations"


def _ok_response(rerun_job_id: str = "job-123") -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"rerun_job_id": rerun_job_id, "queued_count": 0, "skipped_count": 0}
    return response


def _error_response(status_code: int = 500, text: str = "boom") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


class TestRerunGoogleAdsFailedInvocations(BaseTest):
    def setUp(self):
        super().setUp()
        # `HogFunction.save()` fires a reload signal that would try to talk to the CDP
        # API; silence it for the whole class so fixtures don't require the network.
        patcher = patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_fn(self, *, template_id: str, enabled: bool, deleted: bool, name: str = "gads") -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name=name,
            type="destination",
            template_id=template_id,
            enabled=enabled,
            deleted=deleted,
        )

    def test_only_targets_active_non_deleted_google_ads_destinations(self):
        # Regression this catches: if someone drops `enabled=True` or `deleted=False`
        # from the queryset, we'd fire rerun requests at destinations the customer has
        # intentionally turned off (or worse, deleted) after the outage. Also asserts
        # the rerun payload carries status=[failed] + error_kind=[http_4xx] — without
        # both, this command would replay every historical Google Ads send in the
        # window, not just the ones that hit the 401 during the incident.
        target = self._make_fn(template_id="template-google-ads", enabled=True, deleted=False, name="active-gads")
        self._make_fn(template_id="template-google-ads", enabled=False, deleted=False, name="disabled-gads")
        self._make_fn(template_id="template-google-ads", enabled=True, deleted=True, name="deleted-gads")
        self._make_fn(template_id="template-meta-ads", enabled=True, deleted=False, name="not-google")

        with patch(RERUN_HELPER, return_value=_ok_response()) as mock_rerun:
            call_command(
                "rerun_google_ads_failed_invocations",
                "--window-start=2026-07-02T00:00:00Z",
                "--window-end=2026-07-02T12:00:00Z",
                stdout=StringIO(),
            )

        mock_rerun.assert_called_once()
        kwargs = mock_rerun.call_args.kwargs
        self.assertEqual(kwargs["team_id"], target.team_id)
        self.assertEqual(kwargs["function_kind"], "hog_function")
        self.assertEqual(kwargs["function_id"], str(target.id))

        payload_filter = kwargs["payload"]["filter"]
        self.assertEqual(payload_filter["status"], ["failed"])
        self.assertEqual(payload_filter["error_kind"], ["http_4xx"])
        self.assertEqual(payload_filter["window_start"], "2026-07-02T00:00:00+00:00")
        self.assertEqual(payload_filter["window_end"], "2026-07-02T12:00:00+00:00")

    def test_dry_run_does_not_call_rerun_endpoint(self):
        # Regression this catches: --dry-run silently firing real requests would
        # trigger an unintended production rerun during incident-response
        # rehearsal or verification of the target set.
        self._make_fn(template_id="template-google-ads", enabled=True, deleted=False)

        with patch(RERUN_HELPER) as mock_rerun:
            call_command(
                "rerun_google_ads_failed_invocations",
                "--window-start=2026-07-02T00:00:00Z",
                "--window-end=2026-07-02T12:00:00Z",
                "--dry-run",
                stdout=StringIO(),
            )

        mock_rerun.assert_not_called()

    def test_continues_when_one_request_fails(self):
        # Regression this catches: an early 500 from the plugin server halting
        # the whole batch would strand every subsequent team un-retried. The
        # command must call all N destinations regardless.
        self._make_fn(template_id="template-google-ads", enabled=True, deleted=False, name="fn-a")
        self._make_fn(template_id="template-google-ads", enabled=True, deleted=False, name="fn-b")

        with patch(RERUN_HELPER, side_effect=[_error_response(500, "boom"), _ok_response("job-b")]) as mock_rerun:
            call_command(
                "rerun_google_ads_failed_invocations",
                "--window-start=2026-07-02T00:00:00Z",
                "--window-end=2026-07-02T12:00:00Z",
                stdout=StringIO(),
            )

        self.assertEqual(mock_rerun.call_count, 2)
