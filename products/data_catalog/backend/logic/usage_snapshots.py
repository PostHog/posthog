"""Reads of the usage snapshots that the weekly scan writes."""

import dataclasses
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, TypedDict, Unpack
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import posthoganalytics
from pydantic import TypeAdapter
from rest_framework.exceptions import ValidationError

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery
from posthog.hogql.database.schema.information_schema import references_denied_table

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade.api import viewable_dashboard_ids
from products.product_analytics.backend.facade.api import viewable_insight_definitions

from ..facade.contracts import (
    AdjustedRun,
    MetricRunCounts,
    MetricUsage,
    ProposedMetric,
    TableSource,
    TopicCluster,
    TopicDefinition,
    TopicSessionCounts,
    UncoveredGroup,
    UsageSnapshotDetail,
    UsageSnapshotPayload,
    UsageSnapshotSummary,
)
from ..facade.enums import USAGE_FLAG_KEY, UsageSnapshotStatus
from ..models import UsageSnapshot
from .metrics import metrics_visible_to_user
from .usage_proposed_metrics import MAX_CHART_SOURCES
from .validation import table_names_as_written

# A weekly scan writes one row a week, so this is a year of history.
USAGE_HISTORY_LIMIT = 52

SCAN_EXECUTION_TIMEOUT = timedelta(hours=12)
# A row still computing after the scan's execution timeout belongs to a scan that died.
STALE_COMPUTING = SCAN_EXECUTION_TIMEOUT + timedelta(hours=1)
SCAN_STOPPED_MESSAGE = "The scan stopped before it finished."

_PAYLOAD_ADAPTER = TypeAdapter(UsageSnapshotPayload)


def payload_to_json(payload: UsageSnapshotPayload) -> dict[str, Any]:
    return _PAYLOAD_ADAPTER.dump_python(payload, mode="json")


def payload_from_json(data: dict[str, Any]) -> UsageSnapshotPayload:
    return _PAYLOAD_ADAPTER.validate_python(data)


def usage_scans_supported() -> bool:
    """The scan reads MCP telemetry from PostHog's own project on US Cloud, so other deployments cannot scan."""
    return settings.CLOUD_DEPLOYMENT == "US" or settings.DEBUG or settings.TEST


def is_usage_enabled(user: User, team: Team) -> bool:
    return usage_scans_supported() and bool(
        posthoganalytics.feature_enabled(
            USAGE_FLAG_KEY,
            str(user.distinct_id),
            groups={"organization": str(team.organization_id), "project": str(team.uuid)},
            send_feature_flag_events=False,
        )
    )


def usage_snapshot_history(team_id: int) -> list[UsageSnapshotSummary]:
    rows = UsageSnapshot.objects.for_team(team_id).defer("payload").order_by("-created_at")[:USAGE_HISTORY_LIMIT]
    return [_summary(row) for row in rows]


@frozen
class UsageReader:
    """What one caller may see of a snapshot."""

    visible_metric_ids: frozenset[UUID]
    denied_tables: frozenset[str]
    # Without a person, the per-chart access check is skipped.
    team: Team | None = None
    user: User | None = None
    user_access_control: UserAccessControl | None = None


def usage_reader(team: Team, user: User, user_access_control: UserAccessControl) -> UsageReader:
    denied_tables = _denied_tables_and_views(team, user, user_access_control)
    return UsageReader(
        visible_metric_ids=frozenset(
            metrics_visible_to_user(team, user, user_access_control, denied_tables=denied_tables).values_list(
                "id", flat=True
            )
        ),
        denied_tables=frozenset(denied_tables),
        team=team,
        user=user,
        user_access_control=user_access_control,
    )


def _leaf(name: str) -> str:
    """The lowercased last part of a table name. `references_denied_table` matches names this way, so the spread does too."""
    return name.lower().rsplit(".", 1)[-1]


def _denied_tables_and_views(team: Team, user: User, user_access_control: UserAccessControl) -> set[str]:
    """The reader's denied tables, and every view that reads one of them directly or through another view.

    Stored SQL names a view as written, so a view over a denied table must count as denied too.
    """
    database = Database.create_for(team=team, user=user, user_access_control=user_access_control)
    denied = set(database._denied_tables)
    if not denied:
        return denied
    reads: dict[str, frozenset[str] | None] = {}
    for name in database.get_view_names():
        view = database.get_table(name)
        if isinstance(view, SavedQuery):
            reads[name] = _tables_named(view.query)
    # A view that reads a denied table or a denied view is denied, so denials spread through the readers of each view.
    readers: dict[str, list[str]] = defaultdict(list)
    for name, tables in reads.items():
        for table in tables or ():
            readers[_leaf(table)].append(name)
    pending = [
        name
        for name, tables in reads.items()
        if name in denied or tables is None or references_denied_table(sorted(tables), denied)
    ]
    spread: set[str] = set()
    while pending:
        name = pending.pop()
        if name in spread:
            continue
        spread.add(name)
        denied.add(name)
        pending.extend(readers.get(_leaf(name), ()))
    return denied


# A stored query that reaches this length was cut, and the part that was cut can name any table.
STORED_SQL_CHARS = 5000
# The scan keeps only this much of the sample SQL of an uncovered row past the shown rows.
STORED_SAMPLE_SQL_CHARS = 2000


def stored_sql_hidden(sql: str, denied_tables: frozenset[str], *, cut_at: int = STORED_SQL_CHARS) -> bool:
    """Whether a reader with denied tables must not see this stored query. A cut query counts as denied."""
    if not denied_tables:
        return False
    return len(sql) >= cut_at or sql_reads_denied_table(sql, denied_tables)


def sql_reads_denied_table(sql: str, denied_tables: frozenset[str]) -> bool:
    """Whether the SQL names a table the reader cannot read. SQL that does not parse counts as denied."""
    if not denied_tables:
        return False
    tables = _tables_named(sql)
    return tables is None or references_denied_table(sorted(tables), set(denied_tables))


# The cache holds about one large snapshot's stored queries. Each entry keeps its query text on every web worker.
@lru_cache(maxsize=8_000)
def _tables_named(sql: str) -> frozenset[str] | None:
    """The tables a stored query names, or None when it does not parse. Every read checks the same stored rows."""
    try:
        return frozenset(table_names_as_written({"query": sql}, keep_table_functions=True))
    except ValidationError:
        return None


def _group_visible(group: UncoveredGroup, reader: UsageReader) -> bool:
    return (
        (group.matched_metric_id is None or group.matched_metric_id in reader.visible_metric_ids)
        and not stored_sql_hidden(group.sample_sql, reader.denied_tables, cut_at=STORED_SAMPLE_SQL_CHARS)
        and not (group.draft_definition and sql_reads_denied_table(group.draft_definition, reader.denied_tables))
    )


def _proposal_visible(
    proposal: ProposedMetric, shown_measures: set[str], hidden_measures: set[str], reader: UsageReader
) -> bool:
    """A drafted definition need not name the tables its measures read, so a hidden measure hides its proposal.

    For a reader with denied tables the check fails closed: a proposal shows only when it lists measures and
    the reader sees each of them.
    """
    digests = set(proposal.fingerprint_digests)
    if reader.denied_tables and not (digests and digests <= shown_measures):
        return False
    return hidden_measures.isdisjoint(digests) and not sql_reads_denied_table(proposal.definition, reader.denied_tables)


def visible_payload(payload: UsageSnapshotPayload, reader: UsageReader) -> UsageSnapshotPayload:
    """The payload without rows that would show a hidden metric or SQL over a denied table.

    The scan runs as the system, so it stores what every member of the team computed. Each read
    filters that down to what the reader may see.
    """
    uncovered = (
        None if payload.uncovered is None else [group for group in payload.uncovered if _group_visible(group, reader)]
    )
    shown_measures = {group.fingerprint_digest for group in uncovered or []}
    hidden_measures = {group.fingerprint_digest for group in payload.uncovered or []} - shown_measures
    return dataclasses.replace(
        payload,
        metric_runs=None
        if payload.metric_runs is None
        else [counts for counts in payload.metric_runs if counts.metric_id in reader.visible_metric_ids],
        # Topic titles come from every member's questions and carry no source tables to check, so a reader
        # with any denied table gets none.
        topics=None if payload.topics is None else ([] if reader.denied_tables else payload.topics),
        topic_definitions=None
        if payload.topic_definitions is None
        else ([] if reader.denied_tables else payload.topic_definitions),
        table_sources=None
        if payload.table_sources is None
        else [
            source
            for source in payload.table_sources
            if not references_denied_table([source.name], set(reader.denied_tables))
        ],
        uncovered=uncovered,
        proposed_metrics=None
        if payload.proposed_metrics is None
        else [
            proposal
            for proposal in payload.proposed_metrics
            if _proposal_visible(proposal, shown_measures, hidden_measures, reader)
        ],
        adjusted_runs=None
        if payload.adjusted_runs is None
        else [
            run
            for run in payload.adjusted_runs
            if run.metric_id in reader.visible_metric_ids and not stored_sql_hidden(run.sql, reader.denied_tables)
        ],
    )


def latest_usage_snapshot(team_id: int, reader: UsageReader) -> UsageSnapshotDetail | None:
    row = _latest_done(team_id)
    if row is None:
        return None
    detail = _detail(row)
    payload = _viewable_charts(visible_payload(detail.payload, reader), reader)
    return dataclasses.replace(detail, payload=payload)


def _charts_the_reader_may_open(
    proposals: list[ProposedMetric], team: Team, user: User, access: UserAccessControl
) -> list[ProposedMetric]:
    short_ids = {chart.insight_short_id for proposal in proposals for chart in proposal.charts}
    viewable = set(viewable_insight_definitions(team=team, user=user, short_ids=short_ids))
    dashboard_ids = (
        {chart.dashboard_id for proposal in proposals for chart in proposal.charts}
        if access.check_access_level_for_resource("dashboard", "viewer")
        else set()
    )
    # A rule on one dashboard can hide it from a reader who may see dashboards in general.
    viewable_dashboards = viewable_dashboard_ids(
        team_id=team.id,
        dashboard_ids={dashboard_id for dashboard_id in dashboard_ids if dashboard_id is not None},
        user_access_control=access,
    )
    return [
        dataclasses.replace(
            proposal,
            charts=[
                chart
                if chart.dashboard_id in viewable_dashboards
                else dataclasses.replace(chart, dashboard_id=None, dashboard_name=None)
                for chart in proposal.charts
                if chart.insight_short_id in viewable
            ],
        )
        for proposal in proposals
    ]


def _viewable_charts(payload: UsageSnapshotPayload, reader: UsageReader) -> UsageSnapshotPayload:
    """Show the top charts the reader may open, and dashboard names only for a reader who may see dashboards.

    The scan stores more charts than the tab shows, so a chart the reader may not open leaves its place to the next one.
    """
    if not payload.proposed_metrics:
        return payload
    proposals = payload.proposed_metrics
    if reader.user_access_control is not None and reader.team is not None and reader.user is not None:
        proposals = _charts_the_reader_may_open(proposals, reader.team, reader.user, reader.user_access_control)
    return dataclasses.replace(
        payload,
        proposed_metrics=[
            dataclasses.replace(
                proposal,
                charts=proposal.charts[:MAX_CHART_SOURCES],
                other_charts=proposal.other_charts + max(0, len(proposal.charts) - MAX_CHART_SOURCES),
            )
            for proposal in proposals
        ],
    )


def metric_usage(team_id: int, metric_id: UUID, reader: UsageReader) -> MetricUsage | None:
    """The metric's slice of the latest finished scan, or None when no scan has finished.

    A finished scan that counted no run of the metric gives a MetricUsage whose ``runs`` is None.
    """
    row = _latest_done(team_id)
    if row is None:
        return None
    stored = payload_from_json(row.payload)
    # Select the metric's rows first, so the visibility check parses only this metric's SQL.
    payload = visible_payload(
        dataclasses.replace(
            stored,
            metric_runs=None
            if stored.metric_runs is None
            else [counts for counts in stored.metric_runs if counts.metric_id == metric_id],
            adjusted_runs=None
            if stored.adjusted_runs is None
            else [run for run in stored.adjusted_runs if run.metric_id == metric_id],
        ),
        reader,
    )
    runs = next(iter(payload.metric_runs or []), None)
    return MetricUsage(
        metric_id=metric_id,
        snapshot_id=row.id,
        window_start=row.window_start,
        window_end=row.window_end,
        computed_at=row.computed_at,
        runs=runs,
        adjusted_runs=list(payload.adjusted_runs or []),
    )


@frozen
class UsageWindow:
    start: datetime
    end: datetime


def usage_snapshot_window(team_id: int, snapshot_id: UUID) -> UsageWindow:
    row = UsageSnapshot.objects.for_team(team_id).only("window_start", "window_end").get(id=snapshot_id)
    return UsageWindow(start=row.window_start, end=row.window_end)


class PayloadSections(TypedDict, total=False):
    """The sections a scan step can write. Each key must match a ``UsageSnapshotPayload`` field."""

    metric_runs: list[MetricRunCounts]
    conversations: list[list[str]]
    adjusted_runs: list[AdjustedRun]
    topics: list[TopicCluster]
    topic_definitions: list[TopicDefinition]
    topic_sessions: TopicSessionCounts
    table_sources: list[TableSource]
    uncovered: list[UncoveredGroup]
    proposed_metrics: list[ProposedMetric]


def read_payload(team_id: int, snapshot_id: UUID) -> UsageSnapshotPayload:
    return payload_from_json(UsageSnapshot.objects.for_team(team_id).only("payload").get(id=snapshot_id).payload)


def write_payload_sections(team_id: int, snapshot_id: UUID, **sections: Unpack[PayloadSections]) -> None:
    """Replace the named payload sections and keep every other section.

    The row lock makes a section write from one scan step safe against a concurrent write from
    another step on the same snapshot.
    """
    with transaction.atomic():
        row = UsageSnapshot.objects.for_team(team_id).select_for_update().get(id=snapshot_id)
        payload = dataclasses.replace(payload_from_json(row.payload), **sections)
        row.payload = payload_to_json(payload)
        row.save(update_fields=["payload"])


def previous_topic_list(team_id: int, snapshot_id: UUID) -> list[TopicDefinition]:
    """The topic list of the newest finished scan that has one, other than this one.

    A scan before the stored list existed only has its topics with sessions, so those stand in for it.
    """
    row = (
        UsageSnapshot.objects.for_team(team_id)
        .filter(status=UsageSnapshotStatus.DONE.value)
        .filter(Q(payload__topic_definitions__0__isnull=False) | Q(payload__topics__0__isnull=False))
        .exclude(id=snapshot_id)
        .order_by("-computed_at")
        .values_list("payload__topic_definitions", "payload__topics")
        .first()
    )
    if row is None:
        return []
    definitions, topics = row
    return [
        TopicDefinition(title=topic["title"], description=topic.get("description", ""))
        for topic in definitions or topics or []
    ]


def _latest_done(team_id: int) -> UsageSnapshot | None:
    return (
        UsageSnapshot.objects.for_team(team_id)
        .filter(status=UsageSnapshotStatus.DONE.value)
        .order_by("-computed_at")
        .first()
    )


def is_stale(row: UsageSnapshot) -> bool:
    return row.status == UsageSnapshotStatus.COMPUTING.value and row.created_at <= timezone.now() - STALE_COMPUTING


def _status_of(row: UsageSnapshot) -> tuple[UsageSnapshotStatus, str]:
    # A dead scan never closes its row, so the read reports it as failed instead of computing forever.
    if is_stale(row):
        return UsageSnapshotStatus.ERROR, SCAN_STOPPED_MESSAGE
    return UsageSnapshotStatus(row.status), row.error_message


def _summary(row: UsageSnapshot) -> UsageSnapshotSummary:
    status, error_message = _status_of(row)
    return UsageSnapshotSummary(
        id=row.id,
        status=status,
        error_message=error_message,
        window_start=row.window_start,
        window_end=row.window_end,
        judge_model=row.judge_model,
        computed_at=row.computed_at,
        created_at=row.created_at,
    )


def _detail(row: UsageSnapshot) -> UsageSnapshotDetail:
    return UsageSnapshotDetail(**dataclasses.asdict(_summary(row)), payload=payload_from_json(row.payload))
