from collections import defaultdict
from dataclasses import dataclass

from posthog.schema import HogQLFixAction, HogQLFixEdit, HogQLNotice

from posthog.hogql import ast
from posthog.hogql.partition_pruning import (
    UNPRUNED_SCAN_FIX,
    UNPRUNED_SCAN_FIX_TITLE,
    UNPRUNED_SCAN_MESSAGE,
    find_unpruned_events_scans,
)


@dataclass(frozen=True)
class SubqueryFingerprint:
    table_names: tuple[str, ...]
    where: str | None


class MetadataHeuristic:
    def run(self, query: ast.SelectQuery | ast.SelectSetQuery) -> list[HogQLNotice]:
        raise NotImplementedError()


class SimilarSubqueryHeuristic(MetadataHeuristic):
    def run(self, query: ast.SelectQuery | ast.SelectSetQuery) -> list[HogQLNotice]:
        subqueries = _collect_join_subqueries(query)
        if not subqueries:
            return []

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

        return warnings


class UnprunedEventsScanHeuristic(MetadataHeuristic):
    def run(self, query: ast.SelectQuery | ast.SelectSetQuery) -> list[HogQLNotice]:
        warnings: list[HogQLNotice] = []
        for scan in find_unpruned_events_scans(query):
            if scan.start is None:
                continue
            warnings.append(
                HogQLNotice(
                    start=scan.start,
                    end=scan.end,
                    message=f"{UNPRUNED_SCAN_MESSAGE} {UNPRUNED_SCAN_FIX}",
                    fix_action=(
                        HogQLFixAction(
                            title=UNPRUNED_SCAN_FIX_TITLE,
                            edits=[
                                HogQLFixEdit(start=edit.start, end=edit.end, text=edit.text)
                                for edit in scan.bound_edits
                            ],
                        )
                        if scan.bound_edits
                        else None
                    ),
                )
            )
        return warnings


def run_metadata_heuristics(
    query: ast.SelectQuery | ast.SelectSetQuery, *, is_posthog_source: bool = True
) -> list[HogQLNotice]:
    """Run the metadata heuristics over `query`.

    `is_posthog_source` is False for a direct external connection, where a table named `events` is the
    customer's own Postgres or Snowflake table. The partition heuristic reasons about PostHog's
    `sharded_events` schema, so it would describe a partition key that table does not have.
    """
    heuristics: list[MetadataHeuristic] = [SimilarSubqueryHeuristic()]
    if is_posthog_source:
        heuristics.append(UnprunedEventsScanHeuristic())
    warnings: list[HogQLNotice] = []

    for heuristic in heuristics:
        warnings.extend(heuristic.run(query))

    return warnings


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
