import dataclasses
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Optional
from uuid import uuid4

from django.conf import settings

from celery import current_task
from posthoganalytics.client import Client as PostHogClient
from prometheus_client import Gauge
from structlog import get_logger

from posthog.metrics import pushed_metrics_registry

logger = get_logger(__name__)

UsageReportRunSource = Literal["scheduled", "manual", "unknown"]
UsageReportExecutionLocation = Literal["usage_report_worker", "toolbox", "unknown"]
UsageReportExecutionMode = Literal["celery", "direct"]
UsageReportRunScope = Literal["all_orgs", "filtered_orgs"]
UsageReportRunStage = Literal["querying", "sending", "terminal"]
UsageReportTerminalStatus = Literal["completed", "partial_success", "skipped", "failed", "none"]
UsageReportFailureType = Literal["capture", "process", "queue", "producer_unavailable"]
UsageReportCeleryAttemptStatus = Literal["direct", "first_attempt", "retry_attempt", "final_retry", "unknown"]

USAGE_REPORT_RUN_STAGES: tuple[UsageReportRunStage, ...] = ("querying", "sending", "terminal")
USAGE_REPORT_TERMINAL_STATUSES: tuple[UsageReportTerminalStatus, ...] = (
    "completed",
    "partial_success",
    "skipped",
    "failed",
    "none",
)
USAGE_REPORT_FAILURE_TYPES: tuple[UsageReportFailureType, ...] = (
    "capture",
    "process",
    "queue",
    "producer_unavailable",
)
USAGE_REPORT_RUN_STATE_JOB_NAME = "legacy_usage_report_run_state"
USAGE_REPORT_RUN_TERMINAL_TIMESTAMP_JOB_NAME = "legacy_usage_report_run_terminal_timestamp"
USAGE_REPORT_RUN_SUCCESS_TIMESTAMP_JOB_NAME = "legacy_usage_report_run_success_timestamp"
USAGE_REPORT_RUN_METRIC_LABELS = ["region", "source", "execution_location", "execution_mode", "run_scope"]


@dataclasses.dataclass(frozen=True)
class UsageReportCeleryMetadata:
    task_id: Optional[str]
    retries: Optional[int]
    max_retries: Optional[int]


@dataclasses.dataclass(frozen=True)
class UsageReportRunContext:
    run_id: str
    source: UsageReportRunSource
    execution_location: UsageReportExecutionLocation
    execution_mode: UsageReportExecutionMode
    run_scope: UsageReportRunScope
    requested_date: Optional[str]
    period_start: datetime
    period_end: datetime
    region: str
    celery_task_id: Optional[str]
    celery_retries: Optional[int]
    celery_max_retries: Optional[int] = None


@dataclasses.dataclass(frozen=True)
class UsageReportRunStateSnapshot:
    context: UsageReportRunContext
    stage: UsageReportRunStage
    terminal_status: UsageReportTerminalStatus = "none"
    stage_timestamp: float = dataclasses.field(default_factory=lambda: datetime.now(UTC).timestamp())
    total_orgs: Optional[int] = None
    total_orgs_sent: Optional[int] = None
    query_duration_seconds: Optional[float] = None
    total_duration_seconds: Optional[float] = None
    failure_counts: dict[str, int] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class UsageReportRunProgress:
    filtering_properties: dict[str, Any]
    started_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))
    query_started_at: Optional[datetime] = None
    query_finished_at: Optional[datetime] = None
    queue_started_at: Optional[datetime] = None
    queue_finished_at: Optional[datetime] = None
    failure_counts: dict[str, int] = dataclasses.field(default_factory=dict)
    query_duration_seconds: float = 0.0
    queue_duration_seconds: float = 0.0
    total_orgs: int = 0
    total_orgs_sent: int = 0

    @classmethod
    def for_organizations(cls, organization_ids: Optional[Sequence[str]]) -> "UsageReportRunProgress":
        filtering_properties: dict[str, Any] = {"filtered": organization_ids is not None}
        if organization_ids:
            filtering_properties["requested_org_count"] = len(organization_ids)

        return cls(filtering_properties=filtering_properties)

    @property
    def total_duration_seconds(self) -> float:
        return (datetime.now(UTC) - self.started_at).total_seconds()

    @property
    def terminal_status(self) -> UsageReportTerminalStatus:
        return "partial_success" if sum(self.failure_counts.values()) else "completed"

    def start_query_timer(self) -> None:
        self.query_started_at = datetime.now(UTC)

    def finish_query_timer(self) -> None:
        if not self.query_started_at:
            return

        self.query_finished_at = datetime.now(UTC)
        self.query_duration_seconds = (self.query_finished_at - self.query_started_at).total_seconds()

    def start_queue_timer(self) -> None:
        self.queue_started_at = datetime.now(UTC)

    def finish_queue_timer(self) -> None:
        if not self.queue_started_at:
            return

        self.queue_finished_at = datetime.now(UTC)
        self.queue_duration_seconds = (self.queue_finished_at - self.queue_started_at).total_seconds()

    def refresh_active_timers(self) -> None:
        now = datetime.now(UTC)
        if self.query_started_at and not self.query_finished_at:
            self.query_duration_seconds = (now - self.query_started_at).total_seconds()
        if self.queue_started_at and not self.queue_finished_at:
            self.queue_duration_seconds = (now - self.queue_started_at).total_seconds()

    def record_failure(self, failure_type: UsageReportFailureType) -> None:
        self.failure_counts[failure_type] = self.failure_counts.get(failure_type, 0) + 1


@dataclasses.dataclass(frozen=True)
class UsageReportRunObserver:
    context: UsageReportRunContext

    @classmethod
    def from_current_task(
        cls,
        *,
        at: Optional[str],
        period_start: datetime,
        period_end: datetime,
        run_source: UsageReportRunSource,
        execution_location: UsageReportExecutionLocation,
        execution_mode: Optional[UsageReportExecutionMode],
        run_scope: UsageReportRunScope,
        region: str,
    ) -> "UsageReportRunObserver":
        celery_metadata = _get_current_usage_report_celery_metadata()
        resolved_execution_mode = execution_mode or ("celery" if celery_metadata.task_id else "direct")
        resolved_execution_location = execution_location

        if resolved_execution_location == "unknown" and resolved_execution_mode == "celery":
            resolved_execution_location = "usage_report_worker"

        context = UsageReportRunContext(
            run_id=celery_metadata.task_id or str(uuid4()),
            source=run_source,
            execution_location=resolved_execution_location,
            execution_mode=resolved_execution_mode,
            run_scope=run_scope,
            requested_date=at,
            period_start=period_start,
            period_end=period_end,
            region=region,
            celery_task_id=celery_metadata.task_id,
            celery_retries=celery_metadata.retries,
            celery_max_retries=celery_metadata.max_retries,
        )
        return cls(context=context)

    @property
    def log_context(self) -> dict[str, Any]:
        return _usage_report_run_log_context(self.context)

    def querying(
        self,
        pha_client: PostHogClient,
        progress: UsageReportRunProgress,
    ) -> None:
        self.push_state("querying", failure_counts=progress.failure_counts)
        self.capture_event(pha_client, "usage reports querying", progress.filtering_properties)

    def sending(self, progress: UsageReportRunProgress) -> None:
        self.push_state(
            "sending",
            total_orgs=progress.total_orgs,
            query_duration_seconds=progress.query_duration_seconds,
            failure_counts=progress.failure_counts,
        )

    def starting(
        self,
        pha_client: PostHogClient,
        progress: UsageReportRunProgress,
    ) -> None:
        self.capture_event(
            pha_client,
            "usage reports starting",
            {
                "total_orgs": progress.total_orgs,
                **progress.filtering_properties,
            },
        )

    def skipped(self, progress: UsageReportRunProgress) -> dict[str, Any]:
        terminal_properties = {
            "stage": "terminal",
            "terminal_status": "skipped",
            "total_orgs": progress.total_orgs,
            "total_orgs_sent": progress.total_orgs_sent,
            "total_duration_seconds": progress.total_duration_seconds,
            "failure_counts": dict(progress.failure_counts),
            **progress.filtering_properties,
        }
        self.push_state(
            "terminal",
            terminal_status="skipped",
            total_orgs=progress.total_orgs,
            total_orgs_sent=progress.total_orgs_sent,
            total_duration_seconds=progress.total_duration_seconds,
            failure_counts=progress.failure_counts,
        )
        return terminal_properties

    def completed(
        self,
        pha_client: PostHogClient,
        progress: UsageReportRunProgress,
    ) -> dict[str, Any]:
        terminal_status = progress.terminal_status
        complete_event_properties = {
            "total_orgs": progress.total_orgs,
            "period_start": self.context.period_start.isoformat(),
            "period_end": self.context.period_end.isoformat(),
            "total_orgs_sent": progress.total_orgs_sent,
            "query_time": progress.query_duration_seconds,
            "queue_time": progress.queue_duration_seconds,
            "total_time": progress.query_duration_seconds + progress.queue_duration_seconds,
            "total_duration_seconds": progress.total_duration_seconds,
            "terminal_status": terminal_status,
            "failure_counts": dict(progress.failure_counts),
            **progress.filtering_properties,
        }
        self.capture_event(pha_client, "usage reports complete", complete_event_properties)

        terminal_properties = self._terminal_properties(
            terminal_status=terminal_status,
            progress=progress,
        )
        self.push_state(
            "terminal",
            terminal_status=terminal_status,
            total_orgs=progress.total_orgs,
            total_orgs_sent=progress.total_orgs_sent,
            query_duration_seconds=progress.query_duration_seconds,
            total_duration_seconds=progress.total_duration_seconds,
            failure_counts=progress.failure_counts,
        )
        return terminal_properties

    def failed(
        self,
        pha_client: Optional[PostHogClient],
        progress: UsageReportRunProgress,
    ) -> dict[str, Any]:
        terminal_properties = self._terminal_properties(
            terminal_status="failed",
            progress=progress,
        )
        if pha_client:
            failed_event_properties = {key: value for key, value in terminal_properties.items() if key != "stage"}
            self.capture_event(pha_client, "usage reports failed", failed_event_properties)

        self.push_state(
            "terminal",
            terminal_status="failed",
            total_orgs=progress.total_orgs,
            total_orgs_sent=progress.total_orgs_sent,
            query_duration_seconds=progress.query_duration_seconds,
            total_duration_seconds=progress.total_duration_seconds,
            failure_counts=progress.failure_counts,
        )
        return terminal_properties

    def push_state(
        self,
        stage: UsageReportRunStage,
        *,
        terminal_status: UsageReportTerminalStatus = "none",
        total_orgs: Optional[int] = None,
        total_orgs_sent: Optional[int] = None,
        query_duration_seconds: Optional[float] = None,
        total_duration_seconds: Optional[float] = None,
        failure_counts: Optional[Mapping[str, int]] = None,
    ) -> None:
        _push_usage_report_run_state(
            UsageReportRunStateSnapshot(
                context=self.context,
                stage=stage,
                terminal_status=terminal_status,
                total_orgs=total_orgs,
                total_orgs_sent=total_orgs_sent,
                query_duration_seconds=query_duration_seconds,
                total_duration_seconds=total_duration_seconds,
                failure_counts=dict(failure_counts or {}),
            )
        )

    def capture_event(
        self,
        pha_client: PostHogClient,
        event: str,
        properties: Optional[Mapping[str, Any]] = None,
    ) -> None:
        try:
            pha_client.capture(
                distinct_id="internal_billing_events",
                event=event,
                properties=_usage_report_run_event_properties(self.context, properties),
                groups={"instance": settings.SITE_URL},
            )
        except Exception as err:
            logger.exception(
                "Failed to capture usage report lifecycle event",
                lifecycle_event=event,
                run_id=self.context.run_id,
                error=err,
            )

    def _terminal_properties(
        self,
        *,
        terminal_status: UsageReportTerminalStatus,
        progress: UsageReportRunProgress,
    ) -> dict[str, Any]:
        return {
            "stage": "terminal",
            "terminal_status": terminal_status,
            "total_orgs": progress.total_orgs,
            "total_orgs_sent": progress.total_orgs_sent,
            "query_time": progress.query_duration_seconds,
            "queue_time": progress.queue_duration_seconds,
            "total_time": progress.query_duration_seconds + progress.queue_duration_seconds,
            "total_duration_seconds": progress.total_duration_seconds,
            "failure_counts": dict(progress.failure_counts),
            **progress.filtering_properties,
        }


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_current_usage_report_celery_metadata() -> UsageReportCeleryMetadata:
    try:
        task_request = getattr(current_task, "request", None)
    except Exception:
        return UsageReportCeleryMetadata(task_id=None, retries=None, max_retries=None)

    task_id = getattr(task_request, "id", None)
    retries = _coerce_optional_int(getattr(task_request, "retries", None))
    max_retries = _coerce_optional_int(getattr(task_request, "max_retries", None))
    if max_retries is None:
        max_retries = _coerce_optional_int(getattr(current_task, "max_retries", None))

    if task_id is not None:
        task_id = str(task_id)
    else:
        retries = None
        max_retries = None

    return UsageReportCeleryMetadata(task_id=task_id, retries=retries, max_retries=max_retries)


def _usage_report_celery_attempt(context: UsageReportRunContext) -> Optional[int]:
    if context.execution_mode != "celery" or context.celery_retries is None:
        return None
    return context.celery_retries + 1


def _usage_report_celery_attempt_status(context: UsageReportRunContext) -> UsageReportCeleryAttemptStatus:
    if context.execution_mode != "celery":
        return "direct"
    if context.celery_retries is None:
        return "unknown"
    if context.celery_retries == 0:
        return "first_attempt"
    if context.celery_max_retries is not None and context.celery_retries >= context.celery_max_retries:
        return "final_retry"
    return "retry_attempt"


def _usage_report_run_log_context(context: UsageReportRunContext) -> dict[str, Any]:
    return {
        "run_id": context.run_id,
        "source": context.source,
        "execution_location": context.execution_location,
        "execution_mode": context.execution_mode,
        "run_scope": context.run_scope,
        "region": context.region,
        "period_start": context.period_start.isoformat(),
        "period_end": context.period_end.isoformat(),
        "requested_date": context.requested_date,
        "celery_task_id": context.celery_task_id,
        "celery_retries": context.celery_retries,
        "celery_max_retries": context.celery_max_retries,
        "celery_attempt": _usage_report_celery_attempt(context),
        "celery_attempt_status": _usage_report_celery_attempt_status(context),
    }


def _usage_report_run_event_properties(
    context: UsageReportRunContext, properties: Optional[Mapping[str, Any]] = None
) -> dict[str, Any]:
    base_properties = _usage_report_run_log_context(context)
    base_properties.update(properties or {})
    return base_properties


def _usage_report_metric_labels(context: UsageReportRunContext) -> dict[str, str]:
    return {
        "region": context.region,
        "source": context.source,
        "execution_location": context.execution_location,
        "execution_mode": context.execution_mode,
        "run_scope": context.run_scope,
    }


def _usage_report_pushgateway_job_name(base_job_name: str, context: UsageReportRunContext) -> str:
    return "_".join(
        [
            base_job_name,
            context.region.lower(),
            context.source,
            context.execution_location,
            context.execution_mode,
            context.run_scope,
        ]
    )


def _usage_report_run_state_job_name(context: UsageReportRunContext) -> str:
    return _usage_report_pushgateway_job_name(USAGE_REPORT_RUN_STATE_JOB_NAME, context)


def _usage_report_terminal_timestamp_job_name(context: UsageReportRunContext) -> str:
    return _usage_report_pushgateway_job_name(USAGE_REPORT_RUN_TERMINAL_TIMESTAMP_JOB_NAME, context)


def _usage_report_success_timestamp_job_name(context: UsageReportRunContext) -> str:
    return _usage_report_pushgateway_job_name(USAGE_REPORT_RUN_SUCCESS_TIMESTAMP_JOB_NAME, context)


def _push_usage_report_sticky_timestamps(snapshot: UsageReportRunStateSnapshot) -> None:
    if snapshot.terminal_status == "none":
        return

    base_labels = _usage_report_metric_labels(snapshot.context)
    with pushed_metrics_registry(_usage_report_terminal_timestamp_job_name(snapshot.context)) as registry:
        last_terminal_timestamp_gauge = Gauge(
            "posthog_legacy_usage_report_last_terminal_timestamp_seconds",
            "Unix timestamp for the latest legacy usage-report producer terminal state.",
            registry=registry,
            labelnames=USAGE_REPORT_RUN_METRIC_LABELS,
        )
        last_terminal_timestamp_gauge.labels(**base_labels).set(snapshot.stage_timestamp)

    if snapshot.terminal_status == "completed":
        with pushed_metrics_registry(_usage_report_success_timestamp_job_name(snapshot.context)) as registry:
            last_success_timestamp_gauge = Gauge(
                "posthog_legacy_usage_report_last_success_timestamp_seconds",
                "Unix timestamp for the latest completed legacy usage-report producer run.",
                registry=registry,
                labelnames=USAGE_REPORT_RUN_METRIC_LABELS,
            )
            last_success_timestamp_gauge.labels(**base_labels).set(snapshot.stage_timestamp)


def _push_usage_report_run_state(snapshot: UsageReportRunStateSnapshot) -> None:
    try:
        base_labels = _usage_report_metric_labels(snapshot.context)

        with pushed_metrics_registry(_usage_report_run_state_job_name(snapshot.context)) as registry:
            current_stage_gauge = Gauge(
                "posthog_legacy_usage_report_current_stage",
                "Latest legacy usage-report producer stage.",
                registry=registry,
                labelnames=[*USAGE_REPORT_RUN_METRIC_LABELS, "stage"],
            )
            stage_timestamp_gauge = Gauge(
                "posthog_legacy_usage_report_stage_timestamp_seconds",
                "Unix timestamp for the latest legacy usage-report producer stage transition.",
                registry=registry,
                labelnames=[*USAGE_REPORT_RUN_METRIC_LABELS, "stage"],
            )
            terminal_status_gauge = Gauge(
                "posthog_legacy_usage_report_terminal_status",
                "Latest legacy usage-report producer terminal status.",
                registry=registry,
                labelnames=[*USAGE_REPORT_RUN_METRIC_LABELS, "terminal_status"],
            )
            query_duration_gauge = Gauge(
                "posthog_legacy_usage_report_query_duration_seconds",
                "Duration of the usage-report producer query phase for the latest snapshot.",
                registry=registry,
                labelnames=USAGE_REPORT_RUN_METRIC_LABELS,
            )
            total_duration_gauge = Gauge(
                "posthog_legacy_usage_report_total_duration_seconds",
                "Total usage-report producer duration for the latest terminal snapshot.",
                registry=registry,
                labelnames=USAGE_REPORT_RUN_METRIC_LABELS,
            )
            total_orgs_gauge = Gauge(
                "posthog_legacy_usage_report_total_orgs",
                "Total organizations in the latest legacy usage-report producer run.",
                registry=registry,
                labelnames=USAGE_REPORT_RUN_METRIC_LABELS,
            )
            total_orgs_sent_gauge = Gauge(
                "posthog_legacy_usage_report_total_orgs_sent",
                "Organizations sent to Billing by the latest legacy usage-report producer run.",
                registry=registry,
                labelnames=USAGE_REPORT_RUN_METRIC_LABELS,
            )
            failures_gauge = Gauge(
                "posthog_legacy_usage_report_failures",
                "Failure counts for the latest legacy usage-report producer run.",
                registry=registry,
                labelnames=[*USAGE_REPORT_RUN_METRIC_LABELS, "failure_type"],
            )

            for stage in USAGE_REPORT_RUN_STAGES:
                current_stage_gauge.labels(**base_labels, stage=stage).set(1 if snapshot.stage == stage else 0)
                stage_timestamp_gauge.labels(**base_labels, stage=stage).set(
                    snapshot.stage_timestamp if snapshot.stage == stage else 0
                )

            for terminal_status in USAGE_REPORT_TERMINAL_STATUSES:
                terminal_status_gauge.labels(**base_labels, terminal_status=terminal_status).set(
                    1 if snapshot.terminal_status == terminal_status else 0
                )

            query_duration_gauge.labels(**base_labels).set(snapshot.query_duration_seconds or 0)
            total_duration_gauge.labels(**base_labels).set(snapshot.total_duration_seconds or 0)
            total_orgs_gauge.labels(**base_labels).set(snapshot.total_orgs or 0)
            total_orgs_sent_gauge.labels(**base_labels).set(snapshot.total_orgs_sent or 0)

            for failure_type in USAGE_REPORT_FAILURE_TYPES:
                failures_gauge.labels(**base_labels, failure_type=failure_type).set(
                    snapshot.failure_counts.get(failure_type, 0)
                )

        _push_usage_report_sticky_timestamps(snapshot)
    except Exception as err:
        logger.exception(
            "Failed to push usage report run state",
            run_id=snapshot.context.run_id,
            stage=snapshot.stage,
            terminal_status=snapshot.terminal_status,
            error=err,
        )
