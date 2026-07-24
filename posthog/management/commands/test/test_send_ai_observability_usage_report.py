from freezegun import freeze_time
from unittest.mock import patch

from django.core.management import call_command

TASK_PATH = "posthog.management.commands.send_ai_observability_usage_report.send_ai_observability_usage_reports"


@freeze_time("2026-07-22T12:00:00Z")
def test_send_ai_observability_usage_report_defaults_to_current_date() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        call_command("send_ai_observability_usage_report")

    mock_send_reports.assert_called_once_with(
        dry_run=False,
        at="2026-07-22",
        organization_ids=None,
    )


@freeze_time("2026-07-22T12:00:00Z")
def test_send_ai_observability_usage_report_preserves_passed_date() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        call_command("send_ai_observability_usage_report", "--date=2026-07-15")

    mock_send_reports.assert_called_once_with(
        dry_run=False,
        at="2026-07-15",
        organization_ids=None,
    )


@freeze_time("2026-07-22T12:00:00Z")
def test_send_ai_observability_usage_report_dry_run_runs_sync_with_dry_run_flag() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        call_command("send_ai_observability_usage_report", "--dry-run")

    mock_send_reports.assert_called_once_with(
        dry_run=True,
        at="2026-07-22",
        organization_ids=None,
    )
    mock_send_reports.delay.assert_not_called()


@freeze_time("2026-07-22T12:00:00Z")
def test_send_ai_observability_usage_report_async_dispatches_delay_with_parsed_org_ids() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        call_command("send_ai_observability_usage_report", "--async", "--org-ids=org-a, org-b,")

    mock_send_reports.delay.assert_called_once_with(
        dry_run=False,
        at="2026-07-22",
        organization_ids=["org-a", "org-b"],
    )
    mock_send_reports.assert_not_called()
