import datetime

from django.contrib.sessions.models import Session
from django.utils import timezone

import dagster

from posthog.dags.common import JobOwners


class ExpiredSessionCleanupConfig(dagster.Config):
    days_expired: int = 7


@dagster.op
def clean_expired_sessions(
    context: dagster.OpExecutionContext,
    config: ExpiredSessionCleanupConfig,
) -> int:
    cutoff = timezone.now() - datetime.timedelta(days=config.days_expired)

    deleted_count, _ = Session.objects.filter(expire_date__lt=cutoff).delete()

    context.log.info(f"Deleted {deleted_count} expired sessions")
    context.add_output_metadata(
        {
            "deleted_count": dagster.MetadataValue.int(deleted_count),
            "cutoff_date": dagster.MetadataValue.text(cutoff.isoformat()),
        }
    )

    return deleted_count


@dagster.job(tags={"owner": JobOwners.TEAM_DJANGO_INFRA.value})
def expired_session_cleanup_job():
    clean_expired_sessions()


@dagster.schedule(
    job=expired_session_cleanup_job,
    cron_schedule="0 4 * * *",
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def expired_session_cleanup_schedule(context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest(
        run_key=f"expired_session_cleanup_{context.scheduled_execution_time.strftime('%Y%m%d')}",
        run_config={
            "ops": {"clean_expired_sessions": {"config": ExpiredSessionCleanupConfig(days_expired=7).model_dump()}}
        },
    )
