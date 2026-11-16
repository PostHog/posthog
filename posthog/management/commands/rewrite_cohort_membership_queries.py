import re
import json
from collections.abc import Callable, Iterator
from typing import Any, Optional

from django.core.management.base import BaseCommand
from django.db.models import F, Max, Model, QuerySet, TextField
from django.db.models.functions import Cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.endpoints.backend.facade.models import EndpointVersion
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight

LEGACY_TABLE = "cohort_membership"
REPLACEMENT_TABLE = "cohort_people"
# `cohort_people` has neither column, and `*` over it returns a different column list.
UNMAPPED_COLUMNS = {"status", "last_updated", "*"}
INSIGHT_BATCH_SIZE = 100_000
# A table-like mention left after the rewrite: not a column qualifier (`cohort_membership.x`), not the alias the
# rewrite adds (`AS cohort_membership`), and not a longer name like `cohort_membership_changed`.
LEFTOVER_MENTION = re.compile(r"(?<![\w.])(?<!AS )(?<!as )cohort_membership\b(?!\.)|posthog\.cohort_membership\b")


@frozen
class SqlRewrite:
    before: str
    after: Optional[str]


@frozen
class RowRewrite:
    source: str
    pk: str
    team_id: int
    rewrites: tuple[SqlRewrite, ...]
    still_mentions_table: bool

    @property
    def changed(self) -> bool:
        return any(rewrite.after is not None for rewrite in self.rewrites)

    @property
    def needs_manual_check(self) -> bool:
        return self.still_mentions_table or any(rewrite.after is None for rewrite in self.rewrites)


class _TableReferences(TraversingVisitor):
    def __init__(self) -> None:
        self.tables: list[tuple[ast.Field, Optional[str]]] = []
        self._cte_scopes: list[set[str]] = []
        self.all_chains: list[list[str | int]] = []
        self.legacy_scope_chains: list[list[str | int]] = []
        self._scopes: list[bool] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self._cte_scopes.append(set(node.ctes or {}))
        join, reads_legacy = node.select_from, False
        while join is not None:
            reads_legacy = reads_legacy or _legacy_table(join) is not None
            join = join.next_join
        self._scopes.append(reads_legacy)
        super().visit_select_query(node)
        self._scopes.pop()
        self._cte_scopes.pop()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table = _legacy_table(node)
        shadowed = (
            table is not None
            and table.chain == [LEGACY_TABLE]
            and any(LEGACY_TABLE in names for names in self._cte_scopes)
        )
        if table is not None and not shadowed:
            self.tables.append((table, node.alias))
        super().visit_join_expr(node)

    def visit_field(self, node: ast.Field) -> None:
        self.all_chains.append(node.chain)
        if self._scopes and self._scopes[-1]:
            self.legacy_scope_chains.append(node.chain)


def _legacy_table(join: ast.JoinExpr) -> Optional[ast.Field]:
    if isinstance(join.table, ast.Field) and join.table.chain in ([LEGACY_TABLE], ["posthog", LEGACY_TABLE]):
        return join.table
    return None


def rewrite_hogql(sql: str) -> Optional[SqlRewrite]:
    """The rewrite of every `cohort_membership` table reference in `sql`, or None if it reads none."""
    if LEGACY_TABLE not in sql:
        return None
    try:
        parsed = parse_select(sql)
    except Exception:
        return SqlRewrite(before=sql, after=None)

    references = _TableReferences()
    references.visit(parsed)
    tables = references.tables
    if not tables:
        return None

    qualifiers = {LEGACY_TABLE} | {alias for _, alias in tables if alias}
    for chain in references.legacy_scope_chains:
        qualified = len(chain) == 2 and chain[0] in qualifiers
        if chain[-1] in UNMAPPED_COLUMNS and (len(chain) == 1 or qualified):
            return SqlRewrite(before=sql, after=None)

    # Columns qualified with the old table name keep resolving through an alias of the same name.
    qualified_by_table_name = any(len(chain) > 1 and chain[0] == LEGACY_TABLE for chain in references.all_chains)
    rewritten = sql
    for table, alias in sorted(tables, key=lambda reference: reference[0].start or 0, reverse=True):
        if table.start is None or table.end is None:
            return SqlRewrite(before=sql, after=None)
        replacement = REPLACEMENT_TABLE
        if alias is None and qualified_by_table_name:
            replacement = f"{REPLACEMENT_TABLE} AS {LEGACY_TABLE}"
        rewritten = rewritten[: table.start] + replacement + rewritten[table.end :]
    return SqlRewrite(before=sql, after=rewritten)


def rewrite_query_nodes(value: Any) -> tuple[Any, list[SqlRewrite]]:
    """Rewrites every HogQLQuery node nested anywhere in a query or a notebook document."""
    if isinstance(value, list):
        results = [rewrite_query_nodes(item) for item in value]
        return [item for item, _ in results], [rewrite for _, rewrites in results for rewrite in rewrites]
    if not isinstance(value, dict):
        return value, []

    rewritten: dict[str, Any] = {}
    rewrites: list[SqlRewrite] = []
    for key, item in value.items():
        rewritten[key], item_rewrites = rewrite_query_nodes(item)
        rewrites.extend(item_rewrites)
    if rewritten.get("kind") == "HogQLQuery" and isinstance(rewritten.get("query"), str):
        rewrite = rewrite_hogql(rewritten["query"])
        if rewrite is not None:
            rewrites.append(rewrite)
            if rewrite.after is not None:
                rewritten["query"] = rewrite.after
    return rewritten, rewrites


def _rewrite_saved_query(value: Any) -> tuple[Any, list[SqlRewrite]]:
    if isinstance(value, dict) and isinstance(value.get("query"), str):
        rewrite = rewrite_hogql(value["query"])
        if rewrite is None:
            return value, []
        if rewrite.after is None:
            return value, [rewrite]
        return {**value, "query": rewrite.after}, [rewrite]
    return value, []


def _rewrite_rows(
    queryset: QuerySet[Any],
    field: str,
    source: str,
    rewrite: Callable[[Any], tuple[Any, list[SqlRewrite]]],
    apply: bool,
    bump_version: bool = False,
) -> Iterator[RowRewrite]:
    model: type[Model] = queryset.model
    matching = queryset.annotate(field_text=Cast(field, TextField())).filter(field_text__contains=LEGACY_TABLE)
    for pk, team_id, value in matching.values_list("pk", "team_id", field):
        new_value, rewrites = rewrite(value)
        still_mentions_table = LEFTOVER_MENTION.search(json.dumps(new_value)) is not None
        if not rewrites and not still_mentions_table:
            continue
        row = RowRewrite(
            source=source,
            pk=str(pk),
            team_id=team_id,
            rewrites=tuple(rewrites),
            still_mentions_table=still_mentions_table,
        )
        if apply and row.changed:
            updates: dict[str, Any] = {field: new_value}
            if bump_version:
                # An editor holding the old version then gets a conflict instead of saving over the rewrite.
                updates["version"] = F("version") + 1
            model._base_manager.filter(pk=pk).update(**updates)
        yield row


def rewrite_cohort_membership_queries(apply: bool) -> Iterator[RowRewrite]:
    max_insight_id = Insight._base_manager.aggregate(max_id=Max("id"))["max_id"] or 0
    # Insights are too many to scan in one statement, so walk them in primary key ranges.
    for low in range(0, max_insight_id + 1, INSIGHT_BATCH_SIZE):
        batch = Insight._base_manager.filter(id__gte=low, id__lt=low + INSIGHT_BATCH_SIZE)
        yield from _rewrite_rows(batch, "query", "insight", rewrite_query_nodes, apply)

    yield from _rewrite_rows(DataWarehouseSavedQuery._base_manager.all(), "query", "view", _rewrite_saved_query, apply)
    yield from _rewrite_rows(
        Notebook._base_manager.all(), "content", "notebook", rewrite_query_nodes, apply, bump_version=True
    )
    yield from _rewrite_rows(
        EndpointVersion._base_manager.all(), "query", "endpoint version", rewrite_query_nodes, apply
    )


class Command(BaseCommand):
    help = "Point saved HogQL that reads the `cohort_membership` table at `cohort_people`."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Write the rewrites. Without it, the command only reports them."
        )

    def handle(self, *args, **options):
        apply: bool = options["apply"]
        changed, manual = 0, 0
        for row in rewrite_cohort_membership_queries(apply=apply):
            changed += row.changed
            manual += row.needs_manual_check
            self.stdout.write(f"{row.source} {row.pk} (team {row.team_id}):")
            if row.still_mentions_table:
                self.stdout.write(f"  still names {LEGACY_TABLE} outside a query this command rewrites")
            for rewrite in row.rewrites:
                self.stdout.write(f"  before: {rewrite.before}")
                self.stdout.write(f"  after:  {rewrite.after if rewrite.after is not None else 'NEEDS A MANUAL FIX'}")
        verb = "Rewrote" if apply else "Would rewrite"
        self.stdout.write(f"{verb} {changed} rows. {manual} rows need a manual check.")
