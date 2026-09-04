from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from posthog.schema import HogQLNotice

from posthog.hogql import ast
from posthog.hogql.events_scan import (
    EventsScanReason,
    attributed_events_scans,
    events_seen_with_properties,
    finding_fix,
    finding_message,
)

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

    from posthog.models import Team


@dataclass(frozen=True)
class SubqueryFingerprint:
    table_names: tuple[str, ...]
    where: str | None


@frozen
class MetadataHeuristicNotices:
    warnings: list[HogQLNotice]
    notices: list[HogQLNotice]


class MetadataHeuristic:
    def run(self, query: ast.SelectQuery | ast.SelectSetQuery) -> MetadataHeuristicNotices:
        raise NotImplementedError()


class SimilarSubqueryHeuristic(MetadataHeuristic):
    def run(self, query: ast.SelectQuery | ast.SelectSetQuery) -> MetadataHeuristicNotices:
        subqueries = _collect_join_subqueries(query)
        if not subqueries:
            return MetadataHeuristicNotices(warnings=[], notices=[])

        grouped: dict[SubqueryFingerprint, list[ast.SelectQuery]] = defaultdict(list)
        for subquery in subqueries:
            grouped[_fingerprint_select_query(subquery)].append(subquery)

        warnings: list[HogQLNotice] = []
        for similar_queries in grouped.values():
            similar_count = len(similar_queries) - 1
            if similar_count <= 0:
                continue

            similar_subquery_label = "other subquery" if similar_count == 1 else "other subqueries"

            for similar_query in similar_queries:
                if similar_query.start is None:
                    continue

                warnings.append(
                    HogQLNotice(
                        start=similar_query.start,
                        end=similar_query.start + 6,
                        message=(
                            f"This subquery is very similar to {similar_count} {similar_subquery_label}. "
                            "You can usually make this query faster by combining repeated table scans."
                        ),
                    )
                )

        return MetadataHeuristicNotices(warnings=warnings, notices=[])


class EventsScanHeuristic(MetadataHeuristic):
    """Warn when a SELECT reads `events` without a filter the sort key can use.

    A property filter with no event name filter, or a missing timestamp bound, is a warning:
    the query does far more work than the same question needs. Reading every event with no
    filter at all is often the point of the query, so that is only a notice.
    """

    def __init__(
        self,
        team: "Team | None",
        database: "Database",
        as_written: ast.SelectQuery | ast.SelectSetQuery | None = None,
        without_test_accounts: Callable[[], ast.SelectQuery | ast.SelectSetQuery | None] | None = None,
    ) -> None:
        self.team = team
        self.database = database
        # The query text and its expansion with the test-account filters off, to say where an injected filter came from
        self.as_written = as_written
        self.without_test_accounts = without_test_accounts

    def run(self, query: ast.SelectQuery | ast.SelectSetQuery) -> MetadataHeuristicNotices:
        findings = attributed_events_scans(query, self.database, self.as_written, self.without_test_accounts)
        property_names = [name for finding in findings for name in finding.property_names]
        events_by_property = (
            events_seen_with_properties(self.team, property_names) if self.team and property_names else {}
        )

        result = MetadataHeuristicNotices(warnings=[], notices=[])
        for finding in findings:
            notice = HogQLNotice(
                message=finding_message(finding, events_by_property),
                start=finding.start,
                end=finding.end,
                fix=finding_fix(finding),
            )
            if finding.reason == EventsScanReason.NO_EVENT_FILTER:
                result.notices.append(notice)
            else:
                result.warnings.append(notice)
        return result


def run_metadata_heuristics(
    query: ast.SelectQuery | ast.SelectSetQuery,
    team: "Team | None" = None,
    database: "Database | None" = None,
    as_written: ast.SelectQuery | ast.SelectSetQuery | None = None,
    without_test_accounts: Callable[[], ast.SelectQuery | ast.SelectSetQuery | None] | None = None,
) -> MetadataHeuristicNotices:
    heuristics: list[MetadataHeuristic] = [SimilarSubqueryHeuristic()]
    # The events scan check resolves table names, which needs a database not every caller has
    if database is not None:
        heuristics.append(EventsScanHeuristic(team, database, as_written, without_test_accounts))
    result = MetadataHeuristicNotices(warnings=[], notices=[])

    for heuristic in heuristics:
        heuristic_result = heuristic.run(query)
        result.warnings.extend(heuristic_result.warnings)
        result.notices.extend(heuristic_result.notices)

    return result


def _collect_join_subqueries(query: ast.SelectQuery | ast.SelectSetQuery) -> list[ast.SelectQuery]:
    queries = query.select_queries() if isinstance(query, ast.SelectSetQuery) else [query]
    subqueries: list[ast.SelectQuery] = []

    for select_query in queries:
        join = select_query.select_from
        while join:
            if isinstance(join.table, ast.SelectQuery):
                subqueries.append(join.table)
                subqueries.extend(_collect_join_subqueries(join.table))
            elif isinstance(join.table, ast.SelectSetQuery):
                subqueries.extend(_collect_join_subqueries(join.table))
            join = join.next_join

    return subqueries


def _fingerprint_select_query(query: ast.SelectQuery) -> SubqueryFingerprint:
    table_names = _collect_table_names_from_join(query.select_from)
    where = query.where.to_hogql().strip().lower() if query.where else None
    return SubqueryFingerprint(table_names=table_names, where=where)


def _collect_table_names_from_join(join: ast.JoinExpr | None) -> tuple[str, ...]:
    table_names: set[str] = set()

    while join:
        if isinstance(join.table, ast.Field):
            table_names.add(".".join(str(part) for part in join.table.chain).lower())
        join = join.next_join

    return tuple(sorted(table_names))
