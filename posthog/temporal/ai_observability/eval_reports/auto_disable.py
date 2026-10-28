from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.models import User

    from products.ai_observability.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun

logger = structlog.get_logger(__name__)


def disable_undeliverable_report(report: EvaluationReport, report_run: EvaluationReportRun) -> None:
    """Disable a report that no delivery target can receive, so it stops generating, and tell its creator."""
    from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

    # Compare-and-swap so that only one of two racing runs sends the notifications.
    if not EvaluationReport.objects.filter(pk=report.pk, team_id=report.team_id, enabled=True).update(enabled=False):
        return
    report.enabled = False
    logger.warning("llma_eval_reports_auto_disabled", report_id=str(report.pk), team_id=report.team_id)

    creator = _notification_recipient(report)
    if creator is None:
        return

    for notify in (_create_in_app_notification, _send_email):
        # Disabling is the durable outcome. A failed notification must not fail the delivery activity.
        try:
            notify(report, report_run, creator)
        except Exception as e:
            capture_exception(e)
            logger.warning(
                "llma_eval_reports_auto_disabled_notification_failed",
                report_id=str(report.pk),
                notifier=notify.__name__,
                exc_info=True,
            )


def _notification_recipient(report: EvaluationReport) -> User | None:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

    creator = report.created_by
    if creator is None:
        return None
    if not report.team.all_users_with_access().filter(id=creator.id).exists():
        return None
    if not UserAccessControl(creator, report.team).check_access_level_for_object(report.evaluation, "viewer"):
        return None
    return creator


def _evaluation_path(report: EvaluationReport) -> str:
    return f"/project/{report.team_id}/ai-evals/evaluations/{report.evaluation_id}"


def _create_in_app_notification(report: EvaluationReport, report_run: EvaluationReportRun, creator: User) -> None:
    from products.notifications.backend.facade.api import (
        NotificationData,
        NotificationType,
        Priority,
        TargetType,
        create_notification,
    )

    create_notification(
        NotificationData(
            team_id=report.team_id,
            notification_type=NotificationType.PIPELINE_FAILURE,
            priority=Priority.NORMAL,
            title=f"Report for {report.evaluation.name[:75]} was automatically disabled",
            body=(
                "PostHog automatically disabled this report because none of its destinations could receive it. "
                f"{' '.join(report_run.delivery_errors)} "
                "Turn the report back on after you fix this."
            ),
            target_type=TargetType.USER,
            target_id=str(creator.id),
            resource_type="evaluation",
            resource_id=str(report.evaluation_id),
            source_url=_evaluation_path(report),
            idempotency_key=f"llma_eval_report_disabled_{report_run.pk}",
        )
    )


def _send_email(report: EvaluationReport, report_run: EvaluationReportRun, creator: User) -> None:
    from posthog.email import EmailMessage, is_email_available

    if not is_email_available(with_absolute_urls=True):
        return

    evaluation_name = report.evaluation.name
    message = EmailMessage(
        # Keyed on the run so that a retried activity does not send the email twice.
        campaign_key=f"llma_eval_report_disabled_{report.pk}_{report_run.pk}",
        subject=f'Your report for "{evaluation_name}" has been automatically disabled',
        template_name="ai_observability_evaluation_report_disabled",
        template_context={
            "evaluation_name": evaluation_name,
            "delivery_errors": report_run.delivery_errors,
            "evaluation_url": _evaluation_path(report),
        },
    )
    message.add_user_recipient(creator)
    message.send()
