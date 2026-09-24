import time
from collections.abc import Callable, Collection
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Literal, TypedDict

from django.conf import settings

import structlog
import posthoganalytics
from cachetools import TTLCache, cached
from prometheus_client import Counter, Gauge

from posthog.dataclasses import frozen
from posthog.utils import DayRange

logger = structlog.get_logger(__name__)

SHADOW_FAILURES = Counter("usage_counter_shadow_failures_total", "Usage counter shadow failures", ["caller", "stage"])
SHADOW_MISSING_ORGS = Gauge(
    "usage_counter_shadow_missing_organizations", "Organizations with shadow usage but no report", ["caller"]
)


class UsageCounter(StrEnum):
    EVENTS = "teams_with_event_count_in_period"
    ENHANCED_PERSON_EVENTS = "teams_with_enhanced_persons_event_count_in_period"
    RECORDINGS = "teams_with_recording_count_in_period"
    MOBILE_RECORDINGS = "teams_with_mobile_recording_count_in_period"
    MOBILE_BILLABLE_RECORDINGS = "teams_with_mobile_billable_recording_count_in_period"
    SURVEY_RESPONSES = "teams_with_survey_responses_count_in_period"
    AI_EVENTS = "teams_with_ai_event_count_in_period"
    EXCEPTIONS = "teams_with_exceptions_captured_in_period"
    CDP_INVOCATIONS = "teams_with_cdp_billable_invocations_in_period"
    FEATURE_FLAG_REQUESTS = "teams_with_decide_requests_count_in_period"
    FEATURE_FLAG_LOCAL_EVALUATION_REQUESTS = "teams_with_local_evaluation_requests_count_in_period"
    WORKFLOW_EMAILS = "teams_with_workflow_emails_sent_in_period"
    WORKFLOW_PUSH = "teams_with_workflow_push_sent_in_period"
    WORKFLOW_SMS = "teams_with_workflow_sms_sent_in_period"
    WORKFLOW_INVOCATIONS = "teams_with_workflow_billable_invocations_in_period"
    ROWS_SYNCED = "teams_with_rows_synced_in_period"
    FREE_HISTORICAL_ROWS_SYNCED = "teams_with_free_historical_rows_synced_in_period"
    ROWS_EXPORTED = "teams_with_rows_exported_in_period"
    LOGS_BYTES = "teams_with_logs_bytes_in_period"
    LOGS_RETENTION_30D_BYTES = "teams_with_logs_retention_30d_bytes_in_period"
    AI_CREDITS = "teams_with_ai_credits_used_in_period"
    SIGNALS_CREDITS = "teams_with_signals_credits_used_in_period"
    POSTHOG_CODE_CREDITS = "teams_with_posthog_code_credits_used_in_period"
    REPLAY_VISION_CREDITS = "teams_with_replay_vision_credits_used_in_period"


UsageCounterQuery = Callable[[datetime, datetime], list[tuple[int, int]]]


class UsageCounterMode(StrEnum):
    LEGACY = "legacy"
    BOTH = "both"
    REALTIME = "realtime"


UsageCounterCaller = Literal["daily_report", "usage_reports_v2", "quota_limiting"]


@frozen
class UsageRecordTotal:
    team_id: int
    organization_id: str
    usage_key: str
    quantity: int


RECORD_USAGE_KEYS = {
    UsageCounter.EVENTS: "events",
    UsageCounter.ENHANCED_PERSON_EVENTS: "enhanced_person_events",
    UsageCounter.RECORDINGS: "session_replay_recordings",
    UsageCounter.MOBILE_RECORDINGS: "mobile_replay_recordings",
    UsageCounter.MOBILE_BILLABLE_RECORDINGS: "mobile_replay_recordings",
    UsageCounter.SURVEY_RESPONSES: "survey_responses",
    UsageCounter.AI_EVENTS: "ai_events",
    UsageCounter.EXCEPTIONS: "exceptions",
    UsageCounter.CDP_INVOCATIONS: "cdp_billable_invocations",
    UsageCounter.FEATURE_FLAG_REQUESTS: "feature_flag_requests",
    UsageCounter.FEATURE_FLAG_LOCAL_EVALUATION_REQUESTS: "feature_flag_local_evaluation_requests",
    UsageCounter.WORKFLOW_EMAILS: "workflow_emails_sent",
    UsageCounter.WORKFLOW_PUSH: "workflow_push_sent",
    UsageCounter.WORKFLOW_SMS: "workflow_sms_sent",
    UsageCounter.WORKFLOW_INVOCATIONS: "workflow_billable_invocations",
}
COUNTER_FLAG_NAMES = {
    UsageCounter.EVENTS: "events",
    UsageCounter.ENHANCED_PERSON_EVENTS: "enhanced-persons",
    UsageCounter.RECORDINGS: "recordings",
    UsageCounter.MOBILE_RECORDINGS: "mobile-recordings",
    UsageCounter.MOBILE_BILLABLE_RECORDINGS: "mobile-billable-recordings",
    UsageCounter.SURVEY_RESPONSES: "survey-responses",
    UsageCounter.AI_EVENTS: "ai-events",
    UsageCounter.EXCEPTIONS: "exceptions",
    UsageCounter.CDP_INVOCATIONS: "cdp-invocations",
    UsageCounter.FEATURE_FLAG_REQUESTS: "feature-flag-requests",
    UsageCounter.FEATURE_FLAG_LOCAL_EVALUATION_REQUESTS: "feature-flag-local-evaluation-requests",
    UsageCounter.WORKFLOW_EMAILS: "workflow-emails",
    UsageCounter.WORKFLOW_PUSH: "workflow-push",
    UsageCounter.WORKFLOW_SMS: "workflow-sms",
    UsageCounter.WORKFLOW_INVOCATIONS: "workflow-invocations",
}


def validate_usage_record_window(period: DayRange) -> None:
    if period.start.tzinfo is None or period.end.tzinfo is None:
        raise ValueError("Usage record windows must be timezone-aware")
    start = period.start.astimezone(UTC)
    end = period.end.astimezone(UTC)
    next_midnight = start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    if end <= start or end > next_midnight:
        raise ValueError("Usage record windows must stay within one UTC day")


@frozen
class UsageCounterPlan:
    period: DayRange
    caller: UsageCounterCaller
    modes: dict[UsageCounter, UsageCounterMode]

    def __post_init__(self) -> None:
        validate_usage_record_window(self.period)

    @property
    def query_names(self) -> set[str]:
        bundles = {
            UsageCounter.EXCEPTIONS: "exceptions_captured",
            UsageCounter.LOGS_RETENTION_30D_BYTES: "logs_retention_bytes",
        }
        return {bundles.get(counter, counter.value) for counter in self.modes}


@frozen
class UsageCounterComparisonRows:
    legacy_by_team: dict[int, int]
    realtime_by_org: dict[str, int]


class UsageCounterComparison(TypedDict):
    legacy: int
    realtime: int


@frozen
class UsageCounterReport:
    counts: dict[str, list[tuple[int, int]]]
    usage_sources: dict[str, UsageCounterMode] | None = None
    # A missing counter means its comparison failed or did not run; empty totals mean a successful zero.
    counter_comparisons: dict[str, UsageCounterComparisonRows] | None = None


def record_shadow_failure(caller: UsageCounterCaller, stage: str) -> None:
    try:
        SHADOW_FAILURES.labels(caller=caller, stage=stage).inc()
    except Exception:
        logger.exception("usage_counter_shadow_metric_failed", caller=caller, stage=stage)


_mode_cache: TTLCache[tuple[UsageCounter, str], UsageCounterMode] = TTLCache(
    maxsize=128, ttl=60, timer=lambda: time.monotonic()
)


@cached(_mode_cache, key=lambda counter, overrides, caller: (counter, overrides), lock=RLock())
def _resolve_counter_mode(counter: UsageCounter, overrides: str, caller: UsageCounterCaller) -> UsageCounterMode:
    flag_name = COUNTER_FLAG_NAMES.get(counter)
    if flag_name is None:
        return UsageCounterMode.LEGACY
    override = dict(item.strip().split(":", 1) for item in overrides.split(",") if ":" in item)
    mode: str | bool | None
    if flag_name in override:
        mode = override[flag_name].strip()
    else:
        try:
            mode = posthoganalytics.get_feature_flag(f"usage-counter-realtime-{flag_name}", "internal_billing_events")
        except Exception:
            logger.exception("usage_counter_flag_resolution_failed", counter=counter)
            record_shadow_failure(caller, "flags")
            return UsageCounterMode.LEGACY
    if not isinstance(mode, str):
        return UsageCounterMode.LEGACY
    try:
        return UsageCounterMode(mode)
    except ValueError:
        return UsageCounterMode.LEGACY


def resolve_modes(caller: UsageCounterCaller) -> dict[UsageCounter, UsageCounterMode]:
    return {
        counter: _resolve_counter_mode(counter, settings.USAGE_COUNTER_REALTIME_MODES, caller)
        for counter in UsageCounter
    }


class UsageCounterService:
    def __init__(self) -> None:
        # The legacy query module imports this service for report assembly.
        from posthog.tasks import usage_report

        self._queries: dict[UsageCounter, UsageCounterQuery] = {
            UsageCounter.EVENTS: lambda begin, end: usage_report.get_teams_with_billable_event_count_in_period(
                begin, end, count_distinct=True
            ),
            UsageCounter.ENHANCED_PERSON_EVENTS: lambda begin, end: (
                usage_report.get_teams_with_billable_enhanced_persons_event_count_in_period(
                    begin, end, count_distinct=True
                )
            ),
            UsageCounter.RECORDINGS: lambda begin, end: usage_report.get_teams_with_recording_count_in_period(
                begin, end, snapshot_source="web"
            ),
            UsageCounter.MOBILE_RECORDINGS: lambda begin, end: usage_report.get_teams_with_recording_count_in_period(
                begin, end, snapshot_source="mobile"
            ),
            UsageCounter.MOBILE_BILLABLE_RECORDINGS: usage_report.get_teams_with_mobile_billable_recording_count_in_period,
            UsageCounter.SURVEY_RESPONSES: usage_report.get_teams_with_survey_responses_count_in_period,
            UsageCounter.AI_EVENTS: usage_report.get_teams_with_ai_event_count_in_period,
            UsageCounter.EXCEPTIONS: lambda begin, end: [
                (team_id, count) for team_id, count in self._exceptions_query(begin, end)[1]
            ],
            UsageCounter.CDP_INVOCATIONS: usage_report.get_teams_with_cdp_billable_invocations_in_period,
            UsageCounter.FEATURE_FLAG_REQUESTS: lambda begin, end: (
                usage_report.get_teams_with_feature_flag_requests_count_in_period(
                    begin, end, usage_report.FlagRequestType.DECIDE
                )
            ),
            UsageCounter.FEATURE_FLAG_LOCAL_EVALUATION_REQUESTS: lambda begin, end: (
                usage_report.get_teams_with_feature_flag_requests_count_in_period(
                    begin, end, usage_report.FlagRequestType.LOCAL_EVALUATION
                )
            ),
            UsageCounter.WORKFLOW_EMAILS: usage_report.get_teams_with_workflow_emails_sent_in_period,
            UsageCounter.WORKFLOW_PUSH: usage_report.get_teams_with_workflow_push_sent_in_period,
            UsageCounter.WORKFLOW_SMS: usage_report.get_teams_with_workflow_sms_sent_in_period,
            UsageCounter.WORKFLOW_INVOCATIONS: usage_report.get_teams_with_workflow_billable_invocations_in_period,
            UsageCounter.ROWS_SYNCED: usage_report.get_teams_with_rows_synced_in_period,
            UsageCounter.FREE_HISTORICAL_ROWS_SYNCED: usage_report.get_teams_with_free_historical_rows_synced_in_period,
            UsageCounter.ROWS_EXPORTED: usage_report.get_teams_with_rows_exported_in_period,
            UsageCounter.LOGS_BYTES: usage_report.get_teams_with_logs_bytes_in_period,
            UsageCounter.LOGS_RETENTION_30D_BYTES: lambda begin, end: self._logs_retention_query(begin, end)["30d"],
            UsageCounter.AI_CREDITS: usage_report.get_teams_with_ai_credits_used_in_period,
            UsageCounter.SIGNALS_CREDITS: usage_report.get_teams_with_signals_credits_used_in_period,
            UsageCounter.POSTHOG_CODE_CREDITS: usage_report.get_teams_with_posthog_code_credits_used_in_period,
            UsageCounter.REPLAY_VISION_CREDITS: usage_report.get_teams_with_replay_vision_credits_used_in_period,
        }
        self._quota_events_query = usage_report.get_teams_with_billable_event_count_in_period
        self._exceptions_query = usage_report.get_teams_with_exceptions_captured_in_period
        self._logs_retention_query = usage_report.get_teams_with_logs_retention_bytes_in_period
        self._records_query = usage_report.get_usage_records_in_period

    def resolve_plan(
        self, period: DayRange, *, caller: UsageCounterCaller, counters: Collection[UsageCounter] | None = None
    ) -> UsageCounterPlan:
        modes = resolve_modes(caller)
        return UsageCounterPlan(
            period=period,
            caller=caller,
            modes={counter: mode for counter, mode in modes.items() if counters is None or counter in counters},
        )

    def get_legacy(
        self, counter: UsageCounter, begin: datetime, end: datetime, *, caller: UsageCounterCaller = "daily_report"
    ) -> list[tuple[int, int]]:  # nosemgrep: tuple-return-prefer-dataclass -- Legacy query contract: (team_id, count).
        if caller == "quota_limiting" and counter == UsageCounter.EVENTS:
            return self._quota_events_query(begin, end, count_distinct=False)
        return self._queries[counter](begin, end)

    # nosemgrep: tuple-return-prefer-dataclass -- Report consumers require the legacy (team_id, count) rows.
    def _fetch_legacy(self, plan: UsageCounterPlan) -> dict[str, list[tuple[int, int]]]:
        counts: dict[str, list[tuple[int, int]]] = {}
        for counter, mode in plan.modes.items():
            if counter == UsageCounter.EXCEPTIONS and plan.caller != "quota_limiting":
                # The records have no library breakdown, which reports still need after the total switches.
                libraries, totals = self._exceptions_query(plan.period.start, plan.period.end)
                counts.update(
                    {
                        f"teams_with_{'js_lite' if library == 'web_lite' else library}_exceptions_captured_in_period": [
                            (team_id, count) for team_id, count in rows
                        ]
                        for library, rows in libraries.items()
                    }
                )
                counts[counter.value] = [(team_id, count) for team_id, count in totals]
            elif counter == UsageCounter.LOGS_RETENTION_30D_BYTES:
                counts.update(
                    {
                        f"teams_with_logs_retention_{tier}_bytes_in_period": rows
                        for tier, rows in self._logs_retention_query(plan.period.start, plan.period.end).items()
                    }
                )
            else:
                try:
                    counts[counter.value] = self.get_legacy(
                        counter, plan.period.start, plan.period.end, caller=plan.caller
                    )
                except Exception:
                    if mode != UsageCounterMode.REALTIME:
                        raise
                    logger.exception("usage_counter_legacy_comparison_failed", caller=plan.caller, counter=counter)
                    record_shadow_failure(plan.caller, "legacy_comparison")
        return counts

    def fetch_report(self, period: DayRange, *, plan: UsageCounterPlan | None = None) -> UsageCounterReport:
        if plan is None:
            plan = UsageCounterPlan(
                period=period,
                caller="daily_report",
                modes=dict.fromkeys(UsageCounter, UsageCounterMode.LEGACY),
            )
        if plan.period != period:
            raise ValueError("A usage counter plan cannot be shared across periods")
        counts = self._fetch_legacy(plan)
        record_counters = [counter for counter, mode in plan.modes.items() if mode != UsageCounterMode.LEGACY]
        if not record_counters:
            return UsageCounterReport(counts=counts)
        sources = {counter.value.removeprefix("teams_with_"): mode for counter, mode in plan.modes.items()}
        try:
            rows = self._records_query(
                period, tuple(dict.fromkeys(RECORD_USAGE_KEYS[counter] for counter in record_counters)), plan.caller
            )
        except Exception:
            if UsageCounterMode.REALTIME in plan.modes.values():
                raise
            logger.exception("usage_counter_shadow_scan_failed", caller=plan.caller)
            record_shadow_failure(plan.caller, "scan")
            return UsageCounterReport(counts=counts, usage_sources=sources)
        by_team: dict[str, dict[int, int]] = {RECORD_USAGE_KEYS[counter]: {} for counter in record_counters}
        by_org: dict[str, dict[str, int]] = {key: {} for key in by_team}
        for row in rows:
            teams = by_team[row.usage_key]
            teams[row.team_id] = teams.get(row.team_id, 0) + row.quantity
            orgs = by_org[row.usage_key]
            orgs[row.organization_id] = orgs.get(row.organization_id, 0) + row.quantity
        comparisons: dict[str, UsageCounterComparisonRows] = {}
        for counter in record_counters:
            key = RECORD_USAGE_KEYS[counter]
            if counter.value in counts:
                comparisons[counter.value.removeprefix("teams_with_")] = UsageCounterComparisonRows(
                    legacy_by_team=dict(counts[counter.value]), realtime_by_org=by_org[key]
                )
            if plan.modes[counter] == UsageCounterMode.REALTIME:
                counts[counter.value] = list(by_team[key].items())
        return UsageCounterReport(counts=counts, usage_sources=sources, counter_comparisons=comparisons or None)
