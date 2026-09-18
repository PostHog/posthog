import time_machine
from unittest.mock import patch

from django.core.management import call_command


@time_machine.travel("2026-06-02T12:00:00Z", tick=False)
def test_send_usage_report_defaults_to_current_date() -> None:
    with patch("posthog.management.commands.send_usage_report.send_all_org_usage_reports") as mock_send_reports:
        call_command("send_usage_report")

    mock_send_reports.assert_called_once_with(
        dry_run=None,
        at="2026-06-02",
        skip_capture_event=None,
        organization_ids=None,
    )


@time_machine.travel("2026-06-02T12:00:00Z", tick=False)
def test_send_usage_report_preserves_passed_date() -> None:
    with patch("posthog.management.commands.send_usage_report.send_all_org_usage_reports") as mock_send_reports:
        call_command("send_usage_report", "--date=2026-05-31")

    mock_send_reports.assert_called_once_with(
        dry_run=None,
        at="2026-05-31",
        skip_capture_event=None,
        organization_ids=None,
    )
