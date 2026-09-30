import typing
import importlib
import itertools
import collections.abc

from django.conf import settings

from posthog.dataclasses import frozen


@frozen
class WorkerBagSource:
    """One or more modules to source for one or more task queues.

    Attributes:
        modules: Python module names. Each module is imported to lazy-load
            workflows and activities.
        task_queues: One or more task queues the workflows/activities sourced
            belong to.
        names: When not empty, workflows and activities should be looked up in
            collections from the module matching these names. When empty, they
            are looked up in each module's globals.
    """

    modules: tuple[str, ...]
    task_queues: tuple[str, ...]
    names: tuple[str, ...] = ()


@frozen
class WorkerBag:
    """A bag of workflows and activities.

    Meant to be used to initialize a Temopral Worker.
    """

    workflows: tuple[type, ...] = ()
    activities: tuple[typing.Callable[..., typing.Any], ...] = ()


class WorkerBagCollector:
    """Collects WorkerBags for task queue based on stored sources."""

    def __init__(self, sources: collections.abc.Sequence[WorkerBagSource] = ()) -> None:
        self._sources = tuple(sources)

    def collect(self, task_queue: str, /) -> WorkerBag:
        """Collect a WorkerBag for task_queue.

        Raises:
            ValueError: If there isn't at least one stored source matching the
                given task_queue, and if we don't find anything in a configured
                source's module, as that indicates a configuration error.
        """
        matching = [source for source in self._sources if task_queue in source.task_queues]

        if not matching:
            raise ValueError(f"No sources registered for task queue '{task_queue}'")

        workflows = set()
        activities = set()

        for source in matching:
            for module_name in source.modules:
                module = importlib.import_module(module_name)

                found = False

                obj_iter: collections.abc.Iterable[typing.Any]
                if source.names:
                    obj_iter = itertools.chain.from_iterable(getattr(module, name, ()) for name in source.names)
                else:
                    obj_iter = vars(module).values()

                for obj in obj_iter:
                    if _is_workflow(obj):
                        workflows.add(obj)
                        found = True
                    elif _is_activity(obj):
                        activities.add(obj)
                        found = True

                if not found:
                    raise ValueError(
                        f"Module '{module_name}' contains no workflows or activities. Either the source is wrongly configured, or the module should be removed from the source."
                    )

        return WorkerBag(workflows=tuple(workflows), activities=tuple(activities))


def _is_workflow(any: typing.Any) -> bool:
    """Check if any is a Temporal workflow."""
    return (
        isinstance(any, type)
        and hasattr(any, "__temporal_workflow_definition")
        # Excludes subclasses of Workflows, which Temporal also rejects.
        and any.__temporal_workflow_definition.cls == any
    )


def _is_activity(any: typing.Any) -> bool:
    """Check if any is a Temporal activity."""
    return callable(any) and hasattr(any, "__temporal_activity_definition")


def create_worker_bag_collector() -> WorkerBagCollector:
    # When adding modules to a queue, also add their paths to that fleet's filter in the
    # check_temporal_worker_changes step of .github/workflows/container-images-cd.yml
    return WorkerBagCollector(
        sources=(
            WorkerBagSource(
                modules=("products.batch_exports.backend.temporal.workflows",),
                task_queues=(settings.SYNC_BATCH_EXPORTS_TASK_QUEUE, settings.BATCH_EXPORTS_TASK_QUEUE),
            ),
            WorkerBagSource(
                modules=("products.warehouse_sources.backend.temporal.data_imports.settings",),
                task_queues=(settings.DATA_WAREHOUSE_TASK_QUEUE, settings.DATA_WAREHOUSE_CDP_PRODUCER_TASK_QUEUE),
            ),
            WorkerBagSource(
                modules=("posthog.temporal.data_modeling",),
                task_queues=(settings.DATA_WAREHOUSE_TASK_QUEUE, settings.DATA_MODELING_TASK_QUEUE),
                names=("WORKFLOWS", "ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=(
                    "products.warehouse_sources.backend.temporal.data_imports.table_metadata_settings",
                    "products.warehouse_sources.backend.temporal.data_imports.person_property_sync_job",
                    "products.warehouse_sources.backend.temporal.data_imports.person_property_backfill_job",
                    "products.customer_analytics.backend.temporal.account_property_sync",
                ),
                task_queues=(settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("posthog.temporal.data_modeling",),
                task_queues=(settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,),
                names=("SEMANTIC_ENRICHMENT_WORKFLOWS", "SEMANTIC_ENRICHMENT_ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("products.data_quality.backend.temporal",),
                task_queues=(settings.DATA_MODELING_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=(
                    "posthog.temporal.proxy_service",
                    "posthog.temporal.delete_persons",
                    "posthog.temporal.delete_teams",
                    "posthog.temporal.salesforce_enrichment",
                    "products.product_analytics.backend.temporal",
                    "posthog.temporal.dlq_replay",
                    "posthog.temporal.sync_person_distinct_ids",
                    "posthog.temporal.experiments",
                    "products.experiments.backend.temporal.canary_workflow",
                    "products.experiments.backend.temporal.enrollment_census_workflow",
                    "posthog.temporal.cleanup_property_definitions",
                    "posthog.temporal.backfill_materialized_property",
                    "posthog.temporal.backfill_group_type_created_at",
                    "posthog.temporal.ingestion_acceptance_test",
                    "posthog.temporal.warehouse_sources_queue_partition_management",
                    "posthog.temporal.sync_events_retention",
                    "products.growth.backend.temporal.signup_enrichment",
                    "products.logs.backend.temporal.retention_entitlements",
                    "products.context_layer.backend.temporal",
                ),
                task_queues=(settings.GENERAL_PURPOSE_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=(
                    "products.notebooks.backend.facade.temporal",
                    "products.posthog_ai.backend.temporal.backfill",
                    "products.security.backend.facade.temporal",
                ),
                task_queues=(settings.GENERAL_PURPOSE_TASK_QUEUE,),
                names=("WORKFLOWS", "ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("products.engineering_analytics.backend.facade.temporal",),
                task_queues=(settings.GENERAL_PURPOSE_TASK_QUEUE,),
                names=("JOB_LOGS_WORKFLOWS", "JOB_LOGS_ACTIVITIES", "CI_SIGNALS_WORKFLOWS", "CI_SIGNALS_ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("posthog.temporal.quota_limiting",),
                task_queues=(settings.GENERAL_PURPOSE_TASK_QUEUE,),
                names=("ACTIVITIES",),
            ),
            # Dedicated landing zone for signup enrichment. Defaults to the general-purpose queue name (so it
            # merges into that fleet until a dedicated worker exists); setting SIGNUP_ENRICHMENT_TASK_QUEUE on a
            # worker registers these workflows under the dedicated queue, letting dispatch move there with no code change.
            WorkerBagSource(
                modules=("products.growth.backend.temporal.signup_enrichment",),
                task_queues=(settings.SIGNUP_ENRICHMENT_TASK_QUEUE,),
            ),
            # Canvas builds. CANVAS_BUILD_TASK_QUEUE defaults to the general-purpose queue name (so it merges
            # into that fleet until a dedicated worker exists).
            WorkerBagSource(
                modules=("products.canvas.backend.temporal.registry",),
                task_queues=(settings.CANVAS_BUILD_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("products.experiments.backend.temporal",),
                task_queues=(settings.EXPERIMENTS_RECALCULATION_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("posthog.temporal.health_checks",),
                task_queues=(settings.HEALTH_CHECK_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("products.managed_warehouse.backend.temporal",),
                task_queues=(settings.DUCKLAKE_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=(
                    "posthog.temporal.exports",
                    "products.exports.backend.temporal.subscriptions",
                    "posthog.temporal.alerts",
                    "products.pulse.backend.temporal.registry",
                    "posthog.temporal.sync_events_retention",
                ),
                task_queues=(settings.ANALYTICS_PLATFORM_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=(
                    "products.tasks.backend.temporal",
                    # PostHog Desktop Slack workflows are also registered on MAX_AI_TASK_QUEUE.
                    # First step of merging them onto this queue — once master traffic has
                    # cut over and any in-flight runs have drained, drop them from
                    # AI_WORKFLOWS / AI_ACTIVITIES and flip the start_workflow callers in
                    # products/slack_app to settings.TASKS_TASK_QUEUE.
                    "posthog.temporal.ai.slack_app.posthog_code_slack_mention",
                    "posthog.temporal.ai.slack_app.posthog_code_slack_mention_command",
                    "posthog.temporal.ai.slack_app.activities.messaging",
                    "posthog.temporal.ai.slack_app.posthog_slack_inbox_onboarding",
                    "posthog.temporal.ai.slack_app.slack_app_fork",
                    "posthog.temporal.ai.slack_app.activities.rules",
                    "posthog.temporal.ai.slack_app.slack_app_mention",
                ),
                task_queues=(settings.TASKS_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("products.wizard.backend.temporal",),
                task_queues=(settings.WIZARD_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=(
                    "posthog.temporal.ai.chat_agent",
                    "posthog.temporal.ai.sync_vectors",
                    "posthog.temporal.ai.checkpoint_compaction.workflow",
                    "posthog.temporal.ai.anomaly_investigation.workflow",
                    "posthog.temporal.ai.llm_traces_summaries.summarize_traces",
                    "posthog.temporal.ai.research_agent",
                    "products.posthog_ai.backend.temporal.activities",
                ),
                task_queues=(settings.MAX_AI_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("posthog.temporal.alerts",),
                task_queues=(settings.MAX_AI_TASK_QUEUE,),
                names=("AI_QUEUE_ACTIVITIES",),
            ),
            WorkerBagSource(
                modules=("posthog.temporal.tests.utils.workflow",),
                task_queues=(settings.TEST_TASK_QUEUE,),
                names=("WORKFLOWS", "ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=(
                    "posthog.temporal.quota_limiting",
                    "posthog.temporal.salesforce_enrichment",
                    "posthog.temporal.usage_report",
                    "products.billing_alerts.backend.temporal",
                ),
                task_queues=(settings.BILLING_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=(
                    "products.signals.backend.emission.temporal_settings",
                    "products.business_knowledge.backend.temporal",
                    "products.conversations.backend.temporal",
                    "products.customer_analytics.backend.temporal",
                    "products.review_hog.backend.temporal",
                ),
                task_queues=(settings.VIDEO_EXPORT_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("products.signals.backend.temporal",),
                task_queues=(settings.VIDEO_EXPORT_TASK_QUEUE,),
                names=("WORKFLOWS", "ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=(
                    "posthog.temporal.session_replay.count_playlist_items",
                    "posthog.temporal.session_replay.delete_recordings",
                    "posthog.temporal.session_replay.enforce_max_replay_retention",
                    "posthog.temporal.session_replay.rasterize_recording",
                    "posthog.temporal.session_replay.replay_count_metrics",
                    "posthog.temporal.session_replay.surfacing_score_export_sweep",
                    "posthog.temporal.session_replay.surfacing_scoring_sweep",
                ),
                task_queues=(settings.SESSION_REPLAY_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("products.replay_vision.backend.temporal",),
                task_queues=(settings.REPLAY_VISION_TASK_QUEUE,),
            ),
            # The web-analytics digests share this queue with the PostHog-wide weekly digest: both are
            # weekly crons with the same shape, and the messaging queue they used to sit on has no other
            # workflows left, so a dedicated fleet for them isn't worth its reserved capacity.
            WorkerBagSource(
                modules=(
                    "posthog.temporal.weekly_digest",
                    "products.web_analytics.backend.temporal.weekly_digest.workflows",
                    "products.web_analytics.backend.temporal.digest_notification.workflows",
                ),
                task_queues=(settings.WEEKLY_DIGEST_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("products.data_catalog.backend.facade.temporal",),
                task_queues=(settings.WEEKLY_DIGEST_TASK_QUEUE,),
                names=("WORKFLOWS", "ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("posthog.temporal.ai_observability",),
                task_queues=(settings.LLMA_EVALS_TASK_QUEUE,),
                names=("EVAL_WORKFLOWS", "EVAL_ACTIVITIES", "TAGGER_WORKFLOWS", "TAGGER_ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("posthog.temporal.ai_observability",),
                task_queues=(settings.LLMA_TASK_QUEUE, settings.GENERAL_PURPOSE_TASK_QUEUE),
                names=("WORKFLOWS", "ACTIVITIES"),
            ),
            # MCPA_TASK_QUEUE defaults to the general-purpose queue, so the collector combines these
            # registrations until the environment overrides the setting with a dedicated queue.
            WorkerBagSource(
                modules=("posthog.temporal.mcp_analytics.intent_clustering",),
                task_queues=(settings.MCPA_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=(
                    "products.error_tracking.backend.temporal.weekly_digest.workflow",
                    "products.error_tracking.backend.temporal.recommendations_refresh.workflow",
                    "products.error_tracking.backend.temporal.spike_event_cleanup.workflow",
                    "products.error_tracking.backend.temporal.symbol_set_cleanup.workflow",
                    "products.error_tracking.backend.temporal.alerts.activities",
                    "products.error_tracking.backend.temporal.alerts.workflow",
                ),
                task_queues=(settings.ERROR_TRACKING_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=(
                    "products.error_tracking.backend.temporal.lifecycle.issue_created.activities",
                    "products.error_tracking.backend.temporal.lifecycle.issue_spiking.activities",
                    "products.error_tracking.backend.temporal.lifecycle",
                    "products.error_tracking.backend.temporal.lifecycle.issue_reopened.activities",
                ),
                task_queues=(settings.ERROR_TRACKING_LIFECYCLE_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("posthog.temporal.event_screenshots",),
                task_queues=(settings.EVENT_SCREENSHOTS_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("products.logs.backend.temporal",),
                task_queues=(settings.LOGS_ALERTING_TASK_QUEUE,),
            ),
            # Dedicated queue, never merged with alerting: the tick becomes the scan-heavy
            # rollup writer and must not share pods with the latency-sensitive alert checks.
            WorkerBagSource(
                modules=("products.logs.backend.temporal.volume_tick",),
                task_queues=(settings.LOGS_VOLUME_TICK_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("products.autoresearch.backend.facade.temporal",),
                task_queues=(settings.AUTORESEARCH_TASK_QUEUE,),
                names=("WORKFLOWS", "ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("products.signals.backend.temporal",),
                task_queues=(settings.SELF_DRIVING_TASK_QUEUE,),
                names=("SELF_DRIVING_WORKFLOWS", "SELF_DRIVING_ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("products.stamphog.backend.temporal.registry",),
                task_queues=(settings.STAMPHOG_TASK_QUEUE,),
            ),
            WorkerBagSource(
                modules=("products.alerts.backend.facade.temporal",),
                task_queues=(settings.ALERTS_PLATFORM_SHARED_ORCHESTRATION_TASK_QUEUE,),
                names=("SHARED_ORCHESTRATION_WORKFLOWS", "SHARED_ORCHESTRATION_ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("products.alerts.backend.facade.temporal",),
                task_queues=(settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,),
                names=("EVALUATION_WORKFLOWS", "EVALUATION_ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("products.logs.backend.facade.temporal",),
                task_queues=(settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,),
                names=("SOURCE_EVALUATION_WORKFLOWS", "SOURCE_EVALUATION_ACTIVITIES"),
            ),
            WorkerBagSource(
                modules=("products.alerts.backend.facade.temporal",),
                task_queues=(settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE,),
                names=("DELIVERY_WORKFLOWS", "DELIVERY_ACTIVITIES"),
            ),
        )
    )
