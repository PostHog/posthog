from prometheus_client import Counter, Gauge, Histogram

from posthog.otel_metrics import OtelInstrumentFactory

_ACCOUNT_TRACK_RULE_RUNS = Counter(
    "customer_analytics_account_track_rule_runs_total",
    "Account Track Rule runs by trigger and terminal status",
    labelnames=["trigger", "status"],
)
_ACCOUNT_TRACK_RULE_RUN_DURATION_SECONDS = Histogram(
    "customer_analytics_account_track_rule_run_duration_seconds",
    "Account Track Rule run duration",
    labelnames=["trigger", "status"],
    buckets=(0.5, 1, 2.5, 5, 15, 30, 60, 120, 300, 600, 1_800, 3_600, 7_200),
)
_ACCOUNT_TRACK_RULE_ACCOUNTS = Counter(
    "customer_analytics_account_track_rule_accounts_total",
    "Accounts observed or changed by terminal Account Track Rule runs",
    labelnames=["trigger", "outcome"],
)
_ACCOUNT_TRACK_RULE_COORDINATOR_RUNS = Counter(
    "customer_analytics_account_track_rule_coordinator_runs_total",
    "Account Track Rule coordinator runs by outcome",
    labelnames=["outcome"],
)
_ACCOUNT_TRACK_RULE_COORDINATOR_DURATION_SECONDS = Histogram(
    "customer_analytics_account_track_rule_coordinator_duration_seconds",
    "Account Track Rule coordinator duration",
    labelnames=["outcome"],
    buckets=(0.5, 1, 2.5, 5, 15, 30, 60, 120, 300, 600, 1_800),
)
_ACCOUNT_TRACK_RULE_COORDINATOR_CHILDREN = Counter(
    "customer_analytics_account_track_rule_coordinator_children_total",
    "Account Track Rule coordinator child outcomes",
    labelnames=["outcome"],
)
_ACCOUNT_TRACK_RULE_ENABLED_TEAMS = Gauge(
    "customer_analytics_account_track_rule_enabled_teams",
    "Enabled teams observed by the latest Account Track Rule coordinator run",
)
_ACCOUNT_TRACK_RULE_OVERDUE_TEAMS = Gauge(
    "customer_analytics_account_track_rule_overdue_teams",
    "Enabled teams without an Account Track Rule success in the allowed age",
)
_ACCOUNT_TRACK_RULE_OLDEST_SUCCESS_AGE_SECONDS = Gauge(
    "customer_analytics_account_track_rule_oldest_success_age_seconds",
    "Oldest success, first-attempt, or enablement age among enabled Account Track Rule teams",
)
_ACCOUNT_PROPERTY_SYNC_PHASE_DURATION_SECONDS = Histogram(
    "customer_analytics_account_property_sync_phase_duration_seconds",
    "Account property sync operation duration by phase and segment",
    labelnames=["phase", "segment"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 15, 30, 60, 120, 300, 600, 1_800, 3_600),
)

_otel = OtelInstrumentFactory("customer-analytics-account-track-rules")
_account_property_sync_otel = OtelInstrumentFactory("customer-analytics-account-property-sync")


def record_account_property_sync_phase_duration(*, phase: str, segment: str, duration_seconds: float) -> None:
    labels = {"phase": phase, "segment": segment}
    _ACCOUNT_PROPERTY_SYNC_PHASE_DURATION_SECONDS.labels(**labels).observe(duration_seconds)
    _account_property_sync_otel.record_histogram_twin(
        _ACCOUNT_PROPERTY_SYNC_PHASE_DURATION_SECONDS, duration_seconds, labels
    )


def record_account_track_rule_run(
    *,
    trigger: str,
    status: str,
    duration_seconds: float | None,
    eligible_active: int,
    skipped_churned: int,
    tracked: int,
    ignored: int,
    newly_ignored: int,
    restored: int,
) -> None:
    labels = {"trigger": trigger, "status": status}
    _ACCOUNT_TRACK_RULE_RUNS.labels(**labels).inc()
    _otel.record_counter_twin(_ACCOUNT_TRACK_RULE_RUNS, 1, labels)

    if duration_seconds is not None:
        _ACCOUNT_TRACK_RULE_RUN_DURATION_SECONDS.labels(**labels).observe(duration_seconds)
        _otel.record_histogram_twin(_ACCOUNT_TRACK_RULE_RUN_DURATION_SECONDS, duration_seconds, labels)

    for outcome, count in {
        "eligible_active": eligible_active,
        "skipped_churned": skipped_churned,
        "tracked": tracked,
        "ignored": ignored,
        "newly_ignored": newly_ignored,
        "restored": restored,
    }.items():
        outcome_labels = {"trigger": trigger, "outcome": outcome}
        _ACCOUNT_TRACK_RULE_ACCOUNTS.labels(**outcome_labels).inc(count)
        _otel.record_counter_twin(_ACCOUNT_TRACK_RULE_ACCOUNTS, count, outcome_labels)


def record_account_track_rule_coordinator(
    *,
    outcome: str,
    duration_seconds: float,
    enabled_teams: int,
    started_children: int,
    overlapping_children: int,
    skipped_children: int,
    overdue_teams: int,
    oldest_success_age_seconds: float,
) -> None:
    outcome_labels = {"outcome": outcome}
    _ACCOUNT_TRACK_RULE_COORDINATOR_RUNS.labels(**outcome_labels).inc()
    _otel.record_counter_twin(_ACCOUNT_TRACK_RULE_COORDINATOR_RUNS, 1, outcome_labels)
    _ACCOUNT_TRACK_RULE_COORDINATOR_DURATION_SECONDS.labels(**outcome_labels).observe(duration_seconds)
    _otel.record_histogram_twin(_ACCOUNT_TRACK_RULE_COORDINATOR_DURATION_SECONDS, duration_seconds, outcome_labels)

    for child_outcome, count in {
        "started": started_children,
        "overlapping": overlapping_children,
        "skipped": skipped_children,
    }.items():
        child_labels = {"outcome": child_outcome}
        _ACCOUNT_TRACK_RULE_COORDINATOR_CHILDREN.labels(**child_labels).inc(count)
        _otel.record_counter_twin(_ACCOUNT_TRACK_RULE_COORDINATOR_CHILDREN, count, child_labels)

    _ACCOUNT_TRACK_RULE_ENABLED_TEAMS.set(enabled_teams)
    _ACCOUNT_TRACK_RULE_OVERDUE_TEAMS.set(overdue_teams)
    _ACCOUNT_TRACK_RULE_OLDEST_SUCCESS_AGE_SECONDS.set(oldest_success_age_seconds)
    _otel.record_gauge_twin(_ACCOUNT_TRACK_RULE_ENABLED_TEAMS, enabled_teams)
    _otel.record_gauge_twin(_ACCOUNT_TRACK_RULE_OVERDUE_TEAMS, overdue_teams)
    _otel.record_gauge_twin(_ACCOUNT_TRACK_RULE_OLDEST_SUCCESS_AGE_SECONDS, oldest_success_age_seconds)
