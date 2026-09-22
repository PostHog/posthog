from collections import defaultdict
from dataclasses import dataclass

from posthog.schema import HogQLNotice

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

# Some SDKs used to send the event time as a client-side property as well as on the event itself.
# Both names live in the JSON blob rather than in the `timestamp` column the `events` table is
# partitioned and sorted by, so a range filter on one prunes nothing and the query reads every
# event ever ingested while still looking date-bounded to whoever wrote it.
DEPRECATED_TIMESTAMP_PROPERTIES = frozenset({"$time", "$timestamp"})


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


class DeprecatedTimestampPropertyHeuristic(MetadataHeuristic):
    def run(self, query: ast.SelectQuery | ast.SelectSetQuery) -> list[HogQLNotice]:
        warnings: list[HogQLNotice] = []

        select_queries = _collect_select_queries(query)

        # A CTE may be named `events` and shadow the physical table. This runs before source
        # resolution, so a `FROM events` cannot be told apart from one that reads the CTE. Say
        # nothing for the whole query rather than warn about a scan that may not happen.
        if any("events" in (select_query.ctes or {}) for select_query in select_queries):
            return warnings

        for select_query in select_queries:
            if "events" not in _collect_table_names_from_join(select_query.select_from):
                continue

            for name, node in _deprecated_timestamp_references(select_query).items():
                warnings.append(
                    HogQLNotice(
                        start=node.start,
                        end=node.end,
                        message=(
                            f"'properties.{name}' is a deprecated property, not the event timestamp. "
                            "A filter on it does not reduce the data the query reads, so the query "
                            "scans your full event history. Filter on the 'timestamp' column instead."
                        ),
                    )
                )

        return warnings


def run_metadata_heuristics(query: ast.SelectQuery | ast.SelectSetQuery) -> list[HogQLNotice]:
    heuristics: list[MetadataHeuristic] = [SimilarSubqueryHeuristic(), DeprecatedTimestampPropertyHeuristic()]
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


class _SelectQueryCollector(TraversingVisitor):
    def __init__(self) -> None:
        self.select_queries: list[ast.SelectQuery] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.select_queries.append(node)
        super().visit_select_query(node)


class _DeprecatedTimestampReferenceVisitor(TraversingVisitor):
    def __init__(self) -> None:
        # A range filter names the same property twice, so only the first reference is kept: two
        # identical warnings on one line say nothing the first does not.
        self.references: dict[str, ast.Expr] = {}

    def visit_field(self, node: ast.Field) -> None:
        chain = node.chain
        if (
            len(chain) >= 2
            and chain[-2] == "properties"
            and isinstance(chain[-1], str)
            and chain[-1] in DEPRECATED_TIMESTAMP_PROPERTIES
        ):
            self.references.setdefault(chain[-1], node)
        super().visit_field(node)

    def visit_array_access(self, node: ast.ArrayAccess) -> None:
        if (
            isinstance(node.array, ast.Field)
            and node.array.chain
            and node.array.chain[-1] == "properties"
            and isinstance(node.property, ast.Constant)
            and node.property.value in DEPRECATED_TIMESTAMP_PROPERTIES
        ):
            self.references.setdefault(node.property.value, node)
        super().visit_array_access(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A subquery inside a filter carries its own filters, and `_collect_select_queries` reaches
        # it on its own. Descending here would read the subquery's select list as if the outer query
        # filtered on it.
        pass


def _collect_select_queries(query: ast.SelectQuery | ast.SelectSetQuery) -> list[ast.SelectQuery]:
    collector = _SelectQueryCollector()
    collector.visit(query)
    return collector.select_queries


def _deprecated_timestamp_references(query: ast.SelectQuery) -> dict[str, ast.Expr]:
    """The deprecated names a query filters on, mapped to the reference to mark for each.

    Only the filter clauses are read, because the cost this warns about comes from a predicate that
    prunes nothing.
    """
    visitor = _DeprecatedTimestampReferenceVisitor()
    for clause in (query.where, query.prewhere):
        if clause is not None:
            visitor.visit(clause)
    return visitor.references
