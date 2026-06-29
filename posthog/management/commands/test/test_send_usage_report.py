from freezegun import freeze_time
from unittest.mock import patch

from django.core.management import call_command


@freeze_time("2026-06-02T12:00:00Z")
def test_send_usage_report_defaults_to_current_date() -> None:
    with patch("posthog.management.commands.send_usage_report.send_all_org_usage_reports") as mock_send_reports:
        call_command("send_usage_report")

    mock_send_reports.assert_called_once_with(
        dry_run=None,
        at="2026-06-02",
        skip_capture_event=None,
        organization_ids=None,
        run_source="manual",
        execution_location="toolbox",
        execution_mode="direct",
    )


@freeze_time("2026-06-02T12:00:00Z")
def test_send_usage_report_preserves_passed_date() -> None:
    with patch("posthog.management.commands.send_usage_report.send_all_org_usage_reports") as mock_send_reports:
        call_command("send_usage_report", "--date=2026-05-31")

    mock_send_reports.assert_called_once_with(
        dry_run=None,
        at="2026-05-31",
        skip_capture_event=None,
        organization_ids=None,
        run_source="manual",
        execution_location="toolbox",
        execution_mode="direct",
    )


@freeze_time("2026-06-02T12:00:00Z")
def test_send_usage_report_async_runs_on_usage_report_worker() -> None:
    with (
        patch("posthog.management.commands.send_usage_report.send_all_org_usage_reports") as mock_send_reports,
        patch("builtins.print") as print_mock,
    ):
        mock_send_reports.delay.return_value.id = "usage-report-task-id"
        call_command("send_usage_report", "--date=2026-05-31", "--async=1")

    mock_send_reports.delay.assert_called_once_with(
        dry_run=None,
        at="2026-05-31",
        skip_capture_event=None,
        organization_ids=None,
        run_source="manual",
        execution_location="usage_report_worker",
        execution_mode="celery",
    )
    print_mock.assert_any_call("Started async usage report task usage-report-task-id")
