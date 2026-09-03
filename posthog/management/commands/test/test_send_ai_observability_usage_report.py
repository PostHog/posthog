import pytest
from freezegun import freeze_time
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.tasks.ai_observability_usage_report import usage_report_dispatch_lock_key

TASK_PATH = "posthog.management.commands.send_ai_observability_usage_report.send_ai_observability_usage_reports"

CLAIMED_DATES = ("2026-07-15", "2026-07-16", "2026-07-22")


@pytest.fixture(autouse=True)
def _clear_dispatch_claims() -> None:
    # A dispatch claim deliberately outlives the run that made it, and several tests here dispatch the
    # same frozen date, so a claim left behind would refuse the next test's dispatch. Only these keys
    # are deleted: the test cache is process-local and shared by every test in the process, and a
    # `cache.clear()` would also drop the materialized-column metadata the suite caches there.
    for date in CLAIMED_DATES:
        cache.delete(usage_report_dispatch_lock_key(date))


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


@freeze_time("2026-07-22T12:00:00Z")
def test_second_dispatch_for_the_same_date_is_refused() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        call_command("send_ai_observability_usage_report", "--async")

        with pytest.raises(CommandError, match="already dispatched"):
            call_command("send_ai_observability_usage_report", "--async")

    mock_send_reports.delay.assert_called_once()


@freeze_time("2026-07-22T12:00:00Z")
def test_dispatch_claims_are_scoped_per_date() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        call_command("send_ai_observability_usage_report", "--async", "--date=2026-07-15")
        call_command("send_ai_observability_usage_report", "--async", "--date=2026-07-16")

    assert mock_send_reports.delay.call_count == 2


@freeze_time("2026-07-22T12:00:00Z")
def test_dry_run_does_not_claim_the_date() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        call_command("send_ai_observability_usage_report", "--dry-run")
        call_command("send_ai_observability_usage_report", "--async")

    mock_send_reports.delay.assert_called_once()


@freeze_time("2026-07-22T12:00:00Z")
def test_failed_dispatch_releases_the_claim() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        mock_send_reports.delay.side_effect = [RuntimeError("broker down"), None]

        with pytest.raises(RuntimeError, match="broker down"):
            call_command("send_ai_observability_usage_report", "--async")
        call_command("send_ai_observability_usage_report", "--async")

    assert mock_send_reports.delay.call_count == 2


@freeze_time("2026-07-22T12:00:00Z")
def test_equivalent_date_spellings_share_one_claim() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        call_command("send_ai_observability_usage_report", "--async", "--date=2026-07-15")

        with pytest.raises(CommandError, match="already dispatched"):
            call_command("send_ai_observability_usage_report", "--async", "--date=2026-7-15")

    mock_send_reports.delay.assert_called_once_with(
        dry_run=False,
        at="2026-07-15",
        organization_ids=None,
    )


@freeze_time("2026-07-22T12:00:00Z")
def test_unreadable_date_is_rejected_without_dispatching() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        with pytest.raises(CommandError, match="Could not read"):
            call_command("send_ai_observability_usage_report", "--async", "--date=not-a-date")

    mock_send_reports.delay.assert_not_called()


@freeze_time("2026-07-22T12:00:00Z")
def test_failed_synchronous_run_releases_the_claim() -> None:
    with patch(TASK_PATH) as mock_send_reports:
        mock_send_reports.side_effect = [RuntimeError("clickhouse down"), None]

        with pytest.raises(RuntimeError, match="clickhouse down"):
            call_command("send_ai_observability_usage_report")
        call_command("send_ai_observability_usage_report")

    assert mock_send_reports.call_count == 2
