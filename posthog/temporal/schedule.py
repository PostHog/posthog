import asyncio
from dataclasses import asdict
from datetime import timedelta

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio import common
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleCalendarSpec,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
)

from posthog.temporal.ai_observability.eval_reports.schedule import (
    create_count_trigger_schedule,
    create_eval_reports_schedule,
)
from posthog.temporal.ai_observability.evaluation_clustering.schedule import (
    create_evaluation_clustering_schedule,
    create_evaluation_sampler_schedule,
)
from posthog.temporal.ai_observability.trace_clustering.schedule import (
    create_generation_clustering_coordinator_schedule,
    create_trace_clustering_coordinator_schedule,
)
from posthog.temporal.ai_observability.trace_summarization.schedule import (
    create_batch_generation_summarization_schedule,
    create_batch_trace_summarization_schedule,
)
from posthog.temporal.alerts.schedule import (
    create_cleanup_alert_checks_schedule,
    create_run_investigation_safety_net_schedule,
    create_schedule_due_alert_checks_schedule,
)
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.ducklake.compaction_types import DucklakeCompactionInput
from posthog.temporal.experiments.schedule import (
    create_experiment_regular_metrics_schedules,
    create_experiment_saved_metrics_schedules,
)
from posthog.temporal.health_checks.schedule import create_health_check_schedules
from posthog.temporal.ingestion_acceptance_test.schedule import create_ingestion_acceptance_test_schedule
from posthog.temporal.logs_alerting.schedule import create_logs_alert_check_schedule
from posthog.temporal.mcp_analytics.intent_clustering.schedule import create_intent_clustering_coordinator_schedule
from posthog.temporal.messaging.schedule import create_all_realtime_cohort_calculation_schedules
from posthog.temporal.product_analytics.upgrade_queries_workflow import UpgradeQueriesWorkflowInputs
from posthog.temporal.quota_limiting.run_quota_limiting import RunQuotaLimitingInputs
from posthog.temporal.salesforce_enrichment.stripe_workflow import StripeEnrichmentInputs
from posthog.temporal.salesforce_enrichment.usage_workflow import UsageEnrichmentInputs
from posthog.temporal.salesforce_enrichment.workflow import SalesforceEnrichmentInputs
from posthog.temporal.session_replay.delete_recordings.types import PurgeDeletedMetadataInput
from posthog.temporal.session_replay.enforce_max_replay_retention.types import EnforceMaxReplayRetentionInput
from posthog.temporal.session_replay.gemini_cleanup_sweep import create_gemini_cleanup_sweep_schedule
from posthog.temporal.session_replay.replay_count_metrics.types import ReplayCountMetricsInput
from posthog.temporal.session_replay.summarization_sweep.reconciler import (
    create_summarization_sweep_reconciler_schedule,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.schedule import create_surfacing_scoring_sweep_schedule
from posthog.temporal.sync_events_retention.types import SyncEventsRetentionInput
from posthog.temporal.usage_report.types import RunUsageReportsInputs
from posthog.temporal.warehouse_sources_queue_partition_management.schedule import (
    create_warehouse_sources_queue_partition_management_schedule,
)
from posthog.temporal.weekly_digest.types import WeeklyDigestInput

from products.business_knowledge.backend.temporal.schedule import create_business_knowledge_refresh_coordinator_schedule
from products.conversations.backend.temporal.schedule import create_support_reply_coordinator_schedule
from products.engineering_analytics.backend.facade.temporal import create_github_job_logs_coordinator_schedule
from products.error_tracking.backend.facade.temporal import (
    RecommendationsRefreshInputs,
    create_error_tracking_spike_event_cleanup_schedule,
    create_error_tracking_symbol_set_cleanup_schedule,
)
from products.experiments.backend.temporal.schedule import create_experiment_precompute_canary_schedule
from products.exports.backend.temporal.subscriptions.types import ScheduleAllSubscriptionsWorkflowInputs
from products.replay_vision.backend.temporal.estimates import create_replay_vision_estimates_schedule
from products.replay_vision.backend.temporal.gemini_cleanup_sweep import (
    create_replay_vision_gemini_cleanup_sweep_schedule,
)
from products.replay_vision.backend.temporal.reconciler import create_replay_vision_reconciler_schedule
from products.signals.backend.emission.conversations_schedule import create_conversations_signals_coordinator_schedule
from products.signals.backend.temporal.agentic.schedule import create_signals_scout_coordinator_schedule
from products.tasks.backend.facade.temporal import create_evaluate_code_workstreams_schedule
from products.web_analytics.backend.temporal.digest_notification.types import WADigestNotificationInput
from products.web_analytics.backend.temporal.weekly_digest.types import WAWeeklyDigestInput

from ee.billing.salesforce_enrichment.constants import DEFAULT_CHUNK_SIZE

logger = structlog.get_logger(__name__)


async def cleanup_sync_vectors_schedule(client: Client):
    """Disabled: delete the actions embedding sync schedule. Any in-flight runs die on their own execution_timeout."""
    if await a_schedule_exists(client, "ai-sync-vectors-schedule"):
        await a_delete_schedule(client, "ai-sync-vectors-schedule")


async def create_run_quota_limiting_schedule(client: Client):
    """Create or update the schedule for the RunQuotaLimitingWorkflow.

    This schedule runs every 15 minutes.
    """
    run_quota_limiting_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "run-quota-limiting",
            asdict(RunQuotaLimitingInputs()),
            id="run-quota-limiting-schedule",
            task_queue=settings.BILLING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=["10,25,40,55 * * * *"]),  # Run at minutes 10, 25, 40, and 55 of every hour
    )

    if await a_schedule_exists(client, "run-quota-limiting-schedule"):
        await a_update_schedule(client, "run-quota-limiting-schedule", run_quota_limiting_schedule)
    else:
        await a_create_schedule(
            client, "run-quota-limiting-schedule", run_quota_limiting_schedule, trigger_immediately=False
        )


async def create_schedule_all_subscriptions_schedule(client: Client):
    """Create or update the schedule for the ScheduleAllSubscriptionsWorkflow.

    This schedule runs every hour at the 55th minute to match the original Celery schedule.
    """
    schedule_all_subscriptions_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "schedule-all-subscriptions",
            asdict(ScheduleAllSubscriptionsWorkflowInputs()),
            id="schedule-all-subscriptions-schedule",
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=["55 * * * *"]),  # Run at minute 55 of every hour
        # ALLOW_ALL: if a previous run is still executing, start the new one anyway.
        # Safe because child workflows use deterministic IDs (process-subscription-{id})
        # and Temporal guarantees no two open workflows can share the same ID.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
    )

    if await a_schedule_exists(client, "schedule-all-subscriptions-schedule"):
        await a_update_schedule(client, "schedule-all-subscriptions-schedule", schedule_all_subscriptions_schedule)
    else:
        await a_create_schedule(
            client,
            "schedule-all-subscriptions-schedule",
            schedule_all_subscriptions_schedule,
            trigger_immediately=False,
        )


async def create_upgrade_queries_schedule(client: Client):
    """Create or update the schedule for the UpgradeQueriesWorkflow.

    This schedule runs every 6 hours.
    """
    upgrade_queries_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "upgrade-queries",
            asdict(UpgradeQueriesWorkflowInputs()),
            id="upgrade-queries-schedule",
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=6))]),
    )

    if await a_schedule_exists(client, "upgrade-queries-schedule"):
        await a_update_schedule(client, "upgrade-queries-schedule", upgrade_queries_schedule)
    else:
        await a_create_schedule(client, "upgrade-queries-schedule", upgrade_queries_schedule, trigger_immediately=False)


async def create_salesforce_enrichment_schedule(client: Client):
    """Create or update the schedule for the Salesforce enrichment workflow.

    This schedule runs every Sunday at 2 AM UTC with default chunk size.
    """
    salesforce_enrichment_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "salesforce-enrichment-async",
            SalesforceEnrichmentInputs(chunk_size=DEFAULT_CHUNK_SIZE),
            id="salesforce-enrichment-schedule",
            task_queue=settings.BILLING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Sunday at 2 AM UTC",
                    hour=[ScheduleRange(start=2, end=2)],
                    day_of_week=[ScheduleRange(start=0, end=0)],
                )
            ]
        ),
    )

    if await a_schedule_exists(client, "salesforce-enrichment-schedule"):
        await a_update_schedule(client, "salesforce-enrichment-schedule", salesforce_enrichment_schedule)
    else:
        await a_create_schedule(
            client, "salesforce-enrichment-schedule", salesforce_enrichment_schedule, trigger_immediately=False
        )


async def create_salesforce_usage_enrichment_schedule(client: Client):
    """Create or update the schedule for the Salesforce usage enrichment workflow.

    This schedule runs every Sunday at 6 AM UTC to enrich Salesforce accounts with
    PostHog usage signals.
    """
    salesforce_usage_enrichment_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "salesforce-usage-enrichment",
            asdict(UsageEnrichmentInputs()),
            id="salesforce-usage-enrichment-schedule",
            task_queue=settings.BILLING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Sunday at 6 AM UTC",
                    hour=[ScheduleRange(start=6, end=6)],
                    day_of_week=[ScheduleRange(start=0, end=0)],
                )
            ]
        ),
    )

    if await a_schedule_exists(client, "salesforce-usage-enrichment-schedule"):
        await a_update_schedule(client, "salesforce-usage-enrichment-schedule", salesforce_usage_enrichment_schedule)
    else:
        await a_create_schedule(
            client,
            "salesforce-usage-enrichment-schedule",
            salesforce_usage_enrichment_schedule,
            trigger_immediately=False,
        )


async def create_salesforce_stripe_enrichment_schedule(client: Client):
    """Create or update the schedule for the Salesforce stripe enrichment workflow.

    Runs daily at 4 AM UTC to push Stripe customer data and billing customer
    names to Salesforce Accounts. The workflow is incremental via a Redis
    watermark, so a long backfill run is only expected on the first execution;
    ``SKIP`` prevents the next day's run from starting while a backfill is still
    in progress.
    """
    salesforce_stripe_enrichment_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "salesforce-stripe-enrichment",
            asdict(StripeEnrichmentInputs()),
            id="salesforce-stripe-enrichment-schedule",
            task_queue=settings.BILLING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 4 AM UTC",
                    hour=[ScheduleRange(start=4, end=4)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, "salesforce-stripe-enrichment-schedule"):
        await a_update_schedule(client, "salesforce-stripe-enrichment-schedule", salesforce_stripe_enrichment_schedule)
    else:
        await a_create_schedule(
            client,
            "salesforce-stripe-enrichment-schedule",
            salesforce_stripe_enrichment_schedule,
            trigger_immediately=False,
        )


async def create_enforce_max_replay_retention_schedule(client: Client):
    """Create or update the schedule for the enforce max replay retention workflow.

    This schedule runs daily at 1 AM UTC.
    """
    enforce_max_replay_retention_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "enforce-max-replay-retention",
            EnforceMaxReplayRetentionInput(dry_run=False),
            id="enforce-max-replay-retention-schedule",
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=1,
            ),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 1 AM UTC",
                    hour=[ScheduleRange(start=1, end=1)],
                )
            ]
        ),
    )

    if await a_schedule_exists(client, "enforce-max-replay-retention-schedule"):
        await a_update_schedule(client, "enforce-max-replay-retention-schedule", enforce_max_replay_retention_schedule)
    else:
        await a_create_schedule(
            client,
            "enforce-max-replay-retention-schedule",
            enforce_max_replay_retention_schedule,
            trigger_immediately=False,
        )


async def create_sync_events_retention_schedule(client: Client):
    """Create or update the schedule for the events retention sync workflow.

    Runs daily at 02:22 UTC — an off-the-hour minute so it doesn't pile onto the cluster of jobs that fire at the
    top of the hour.
    """
    sync_events_retention_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "sync-events-retention",
            SyncEventsRetentionInput(dry_run=False),
            id="sync-events-retention-schedule",
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=1,
            ),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 02:22 UTC",
                    hour=[ScheduleRange(start=2, end=2)],
                    minute=[ScheduleRange(start=22, end=22)],
                )
            ]
        ),
    )

    if await a_schedule_exists(client, "sync-events-retention-schedule"):
        await a_update_schedule(client, "sync-events-retention-schedule", sync_events_retention_schedule)
    else:
        await a_create_schedule(
            client,
            "sync-events-retention-schedule",
            sync_events_retention_schedule,
            trigger_immediately=False,
        )


async def create_weekly_digest_schedule(client: Client):
    """Create or update the schedule for the weekly digest workflow.

    This schedule runs weekly at Monday 5 AM UTC.
    """
    weekly_digest_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "weekly-digest",
            WeeklyDigestInput(),
            id="weekly-digest-schedule",
            task_queue=settings.WEEKLY_DIGEST_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=1,
            ),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Weekly at Monday 5 AM UTC",
                    hour=[ScheduleRange(start=5, end=5)],
                    day_of_week=[ScheduleRange(start=1, end=1)],
                )
            ]
        ),
    )

    if await a_schedule_exists(client, "weekly-digest-schedule"):
        await a_update_schedule(client, "weekly-digest-schedule", weekly_digest_schedule)
    else:
        await a_create_schedule(
            client,
            "weekly-digest-schedule",
            weekly_digest_schedule,
            trigger_immediately=False,
        )


async def create_wa_weekly_digest_schedule(client: Client):
    """Create or update the schedule for the WA weekly digest workflow."""
    wa_digest_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "wa-weekly-digest",
            WAWeeklyDigestInput(),
            id="wa-weekly-digest-schedule",
            task_queue=settings.MESSAGING_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=1,
            ),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Weekly at Thursday 5 PM PT",
                    hour=[ScheduleRange(start=17, end=17)],
                    day_of_week=[ScheduleRange(start=4, end=4)],
                )
            ],
            time_zone_name="America/Los_Angeles",
        ),
    )

    if await a_schedule_exists(client, "wa-weekly-digest-schedule"):
        await a_update_schedule(client, "wa-weekly-digest-schedule", wa_digest_schedule)
    else:
        await a_create_schedule(
            client,
            "wa-weekly-digest-schedule",
            wa_digest_schedule,
            trigger_immediately=False,
        )


async def create_wa_digest_notification_schedule(client: Client):
    """Create or update the schedule for the WA digest notification workflow."""
    wa_digest_notification_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "wa-digest-notification",
            WADigestNotificationInput(),
            id="wa-digest-notification-schedule",
            task_queue=settings.MESSAGING_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=1,
            ),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Weekly at Monday 9 AM PT",
                    hour=[ScheduleRange(start=9, end=9)],
                    day_of_week=[ScheduleRange(start=1, end=1)],
                )
            ],
            time_zone_name="America/Los_Angeles",
        ),
    )

    if await a_schedule_exists(client, "wa-digest-notification-schedule"):
        await a_update_schedule(client, "wa-digest-notification-schedule", wa_digest_notification_schedule)
    else:
        await a_create_schedule(
            client,
            "wa-digest-notification-schedule",
            wa_digest_notification_schedule,
            trigger_immediately=False,
        )


async def create_ducklake_compaction_schedule(client: Client):
    """Create or update the schedule for the DuckLake compaction workflow.

    This schedule runs every hour to compact small parquet files in DuckLake.
    """
    ducklake_compaction_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "ducklake-compaction",
            DucklakeCompactionInput(target_file_size="512MB"),
            id="ducklake-compaction-schedule",
            task_queue=settings.DUCKLAKE_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(minutes=5),
            ),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
    )

    if await a_schedule_exists(client, "ducklake-compaction-schedule"):
        await a_update_schedule(client, "ducklake-compaction-schedule", ducklake_compaction_schedule)
    else:
        await a_create_schedule(
            client,
            "ducklake-compaction-schedule",
            ducklake_compaction_schedule,
            trigger_immediately=False,
        )


async def create_purge_deleted_recording_metadata_schedule(client: Client):
    """Create or update the schedule for the purge deleted recording metadata workflow.

    This schedule runs daily at 3 AM UTC to permanently delete ClickHouse metadata
    for recordings that have been deleted.
    """
    purge_deleted_recording_metadata_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "purge-deleted-recording-metadata",
            PurgeDeletedMetadataInput(),
            id="purge-deleted-recording-metadata-schedule",
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(minutes=5),
            ),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 3 AM UTC",
                    hour=[ScheduleRange(start=3, end=3)],
                )
            ]
        ),
    )

    if await a_schedule_exists(client, "purge-deleted-recording-metadata-schedule"):
        await a_update_schedule(
            client, "purge-deleted-recording-metadata-schedule", purge_deleted_recording_metadata_schedule
        )
    else:
        await a_create_schedule(
            client,
            "purge-deleted-recording-metadata-schedule",
            purge_deleted_recording_metadata_schedule,
            trigger_immediately=False,
        )


async def create_replay_count_metrics_schedule(client: Client):
    """Create or update the schedule for the replay count metrics workflow.

    This schedule runs hourly at minute 0, matching the previous Celery schedule.
    """
    replay_count_metrics_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "replay-count-metrics",
            ReplayCountMetricsInput(),
            id="replay-count-metrics-schedule",
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
            ),
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))],
        ),
    )

    if await a_schedule_exists(client, "replay-count-metrics-schedule"):
        await a_update_schedule(client, "replay-count-metrics-schedule", replay_count_metrics_schedule)
    else:
        await a_create_schedule(
            client,
            "replay-count-metrics-schedule",
            replay_count_metrics_schedule,
            trigger_immediately=False,
        )


async def cleanup_legacy_session_summarization_schedules(client: Client):
    """Delete legacy schedules. Any in-flight runs die on their own execution_timeout."""
    legacy_schedule_ids = [
        "video-segment-clustering-coordinator-schedule",
        "session-summarization-sweep-schedule",
    ]
    for schedule_id in legacy_schedule_ids:
        if await a_schedule_exists(client, schedule_id):
            await a_delete_schedule(client, schedule_id)


async def create_run_usage_reports_schedule(client: Client):
    """Intraday usage report run every 3 hours at minute 45 (8 times a day).

    Reports *today's* usage so far (`day_offset=0`) so billing gets fresh
    numbers throughout the day. A failed slot is superseded by the next one
    3 hours later, so no retries. The complete-day capture is handled by the
    daily finalizer schedule (`create_finalize_usage_reports_schedule`). The
    workflow writes per-org usage data to S3 and sends a single SQS pointer
    to the billing service.
    """
    run_usage_reports_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "run-usage-reports",
            # `RunUsageReportsInputs` is a pydantic model, not a dataclass —
            # `dataclasses.asdict` would TypeError on registration.
            RunUsageReportsInputs(day_offset=0).model_dump(mode="json"),
            id="run-usage-reports-schedule",
            task_queue=settings.BILLING_TASK_QUEUE,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Every 3 hours at minute 45 (01:45, 04:45, ..., 22:45 UTC)",
                    hour=[ScheduleRange(start=1, end=22, step=3)],
                    minute=[ScheduleRange(start=45, end=45)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, "run-usage-reports-schedule"):
        await a_update_schedule(client, "run-usage-reports-schedule", run_usage_reports_schedule)
    else:
        await a_create_schedule(
            client,
            "run-usage-reports-schedule",
            run_usage_reports_schedule,
            trigger_immediately=False,
        )


async def create_finalize_usage_reports_schedule(client: Client):
    """Daily finalizer for the usage reports v2 flow, 03:00 UTC.

    Reports *yesterday* (`day_offset=1`) once the day is complete — billing
    treats a `day_offset >= 1` pointer as the final numbers for that date.
    03:00 leaves 3 hours for ingestion lag after midnight while staying clear
    of the legacy Celery run at 03:45 UTC. Unlike the intraday schedule this
    run has no later slot to supersede it, so the retry policy keeps
    re-running it across the day (5m, 10m, ... capped at 2h) until it
    succeeds. Anything longer than that is a manual backfill: trigger the
    workflow with `day_offset=N` for the missed day.
    """
    finalize_usage_reports_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "run-usage-reports",
            RunUsageReportsInputs(day_offset=1).model_dump(mode="json"),
            id="finalize-usage-reports-schedule",
            task_queue=settings.BILLING_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=8,
                initial_interval=timedelta(minutes=5),
                maximum_interval=timedelta(hours=2),
            ),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 03:00 UTC",
                    hour=[ScheduleRange(start=3, end=3)],
                    minute=[ScheduleRange(start=0, end=0)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, "finalize-usage-reports-schedule"):
        await a_update_schedule(client, "finalize-usage-reports-schedule", finalize_usage_reports_schedule)
    else:
        await a_create_schedule(
            client,
            "finalize-usage-reports-schedule",
            finalize_usage_reports_schedule,
            trigger_immediately=False,
        )


async def create_count_all_playlists_schedule(client: Client):
    """Create or update the schedule for the playlist counting workflow.

    This schedule runs hourly at minute 30, matching the previous Celery schedule.
    Uses SKIP overlap policy to prevent overlapping runs.
    """
    count_all_playlists_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "count-all-playlists",
            None,
            id="count-all-playlists-schedule",
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
            ),
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(every=timedelta(hours=1), offset=timedelta(minutes=30)),
            ],
        ),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
        ),
    )

    if await a_schedule_exists(client, "count-all-playlists-schedule"):
        await a_update_schedule(client, "count-all-playlists-schedule", count_all_playlists_schedule)
    else:
        await a_create_schedule(
            client,
            "count-all-playlists-schedule",
            count_all_playlists_schedule,
            trigger_immediately=False,
        )


async def create_error_tracking_recommendations_refresh_schedule(client: Client):
    """Hourly background refresh of error tracking recommendations.

    Sweeps every team that ingested an exception in the last 7 days and re-kicks each
    team's stale recommendations. Each recommendation self-throttles via its own
    ``refresh_interval`` (e.g. source_maps every 6h), so the hourly sweep only recomputes
    what has actually gone stale. SKIP overlap means a slow run never stacks on the next.
    """
    error_tracking_recommendations_refresh_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "error-tracking-recommendations-refresh",
            RecommendationsRefreshInputs(),
            id="error-tracking-recommendations-refresh-schedule",
            task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, "error-tracking-recommendations-refresh-schedule"):
        await a_update_schedule(
            client,
            "error-tracking-recommendations-refresh-schedule",
            error_tracking_recommendations_refresh_schedule,
        )
    else:
        await a_create_schedule(
            client,
            "error-tracking-recommendations-refresh-schedule",
            error_tracking_recommendations_refresh_schedule,
            trigger_immediately=False,
        )


schedules = [
    cleanup_sync_vectors_schedule,
    create_run_quota_limiting_schedule,
    create_upgrade_queries_schedule,
    create_count_all_playlists_schedule,
    create_error_tracking_recommendations_refresh_schedule,
    create_enforce_max_replay_retention_schedule,
    create_sync_events_retention_schedule,
    create_replay_count_metrics_schedule,
    create_weekly_digest_schedule,
    create_batch_trace_summarization_schedule,
    create_batch_generation_summarization_schedule,
    create_trace_clustering_coordinator_schedule,
    create_generation_clustering_coordinator_schedule,
    create_intent_clustering_coordinator_schedule,
    create_eval_reports_schedule,
    create_count_trigger_schedule,
    create_evaluation_sampler_schedule,
    create_evaluation_clustering_schedule,
    cleanup_legacy_session_summarization_schedules,
    create_summarization_sweep_reconciler_schedule,
    create_surfacing_scoring_sweep_schedule,
    create_ducklake_compaction_schedule,
    create_purge_deleted_recording_metadata_schedule,
    create_experiment_regular_metrics_schedules,
    create_experiment_saved_metrics_schedules,
    create_experiment_precompute_canary_schedule,
    create_all_realtime_cohort_calculation_schedules,
    create_ingestion_acceptance_test_schedule,
    create_warehouse_sources_queue_partition_management_schedule,
    create_health_check_schedules,
    create_conversations_signals_coordinator_schedule,
    create_business_knowledge_refresh_coordinator_schedule,
    create_error_tracking_symbol_set_cleanup_schedule,
    create_error_tracking_spike_event_cleanup_schedule,
    create_wa_weekly_digest_schedule,
    create_wa_digest_notification_schedule,
    create_logs_alert_check_schedule,
    create_schedule_due_alert_checks_schedule,
    create_run_investigation_safety_net_schedule,
    create_cleanup_alert_checks_schedule,
    create_signals_scout_coordinator_schedule,
    create_support_reply_coordinator_schedule,
    create_replay_vision_reconciler_schedule,
    create_replay_vision_estimates_schedule,
    create_evaluate_code_workstreams_schedule,
    create_github_job_logs_coordinator_schedule,
]

if settings.CLOUD_DEPLOYMENT:
    # Gemini uploads only happen in cloud; each sweep reaps only the files tracked in this
    # deployment's own Redis index, so per-deployment scoping is inherent.
    schedules.append(create_gemini_cleanup_sweep_schedule)
    schedules.append(create_replay_vision_gemini_cleanup_sweep_schedule)
    schedules.append(create_run_usage_reports_schedule)
    schedules.append(create_finalize_usage_reports_schedule)

if settings.EE_AVAILABLE:
    schedules.append(create_schedule_all_subscriptions_schedule)
    if settings.CLOUD_DEPLOYMENT == "US":
        schedules.append(create_salesforce_enrichment_schedule)
        schedules.append(create_salesforce_usage_enrichment_schedule)
        schedules.append(create_salesforce_stripe_enrichment_schedule)


async def a_init_general_queue_schedules():
    temporal = await async_connect()
    try:
        async with asyncio.TaskGroup() as tg:
            for schedule in schedules:
                tg.create_task(schedule(temporal))
    except* Exception as eg:
        for exc in eg.exceptions:
            logger.exception("Failed to initialize temporal schedules", error=exc)
            if not isinstance(exc, ScheduleAlreadyRunningError):
                raise exc


@async_to_sync
async def init_schedules():
    await a_init_general_queue_schedules()
