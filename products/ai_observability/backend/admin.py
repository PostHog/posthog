from datetime import date

from django.core.management import call_command
from django.core.management.base import CommandError

import structlog

from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.ai_observability_usage_report import internal_reporting_team_id

from products.ai_observability.backend.dataset_retention import RETENTION_ENABLED_SETTING, dataset_retention_enabled

logger = structlog.get_logger(__name__)


class UsageReportRefused(Exception):
    """The usage report run was not queued, for example because a run for the same date was already dispatched."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def set_dataset_retention_enabled(*, enabled: bool, user_id: int) -> None:
    previous_enabled = dataset_retention_enabled()
    set_instance_setting(RETENTION_ENABLED_SETTING, enabled)
    logger.info(
        "dataset_retention_setting_changed", user_id=user_id, previous_enabled=previous_enabled, enabled=enabled
    )


def queue_usage_report(report_date: date) -> None:
    """Queue the usage report of every organization in this region for `report_date`.

    Raises `UsageReportRefused` when the command refuses the date. A swallowed refusal would look like a run that
    started, so staff would stop looking for the missing reports.
    """
    try:
        call_command("send_ai_observability_usage_report", f"--date={report_date.strftime('%Y-%m-%d')}", "--async")
    except CommandError as error:
        raise UsageReportRefused(str(error)) from error


def usage_report_skips_existing_reports() -> bool:
    """Whether a run here can see which organizations already have a report, and skip them."""
    return internal_reporting_team_id() is not None
