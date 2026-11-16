import re
from collections.abc import Callable, Iterator
from typing import Any, Literal, Optional

from django.db.models import QuerySet, TextField
from django.db.models.functions import Cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen

LEGACY_TABLE = "cohort_membership"
REPLACEMENT_TABLE = "cohort_people"
# `cohort_people` has neither column, and `*` over it returns a different column list.
UNMAPPED_COLUMNS = {"status", "last_updated", "*"}
# A table-like mention left after the rewrite: not a column qualifier (`cohort_membership.x`), not the alias the
# rewrite adds (`AS cohort_membership`), and not a longer name like `cohort_membership_changed`.
LEFTOVER_MENTION = re.compile(r"(?<![\w.])(?<!AS )(?<!as )cohort_membership\b(?!\.)|posthog\.cohort_membership\b")

SavedQuerySource = Literal["insight", "view", "notebook", "endpoint version"]


@frozen
class SqlRewrite:
    before: str
    after: Optional[str]

    @property
    def needs_manual_fix(self) -> bool:
        return self.after is None


@frozen
class SavedQueryRewrite:
    source: SavedQuerySource
    pk: str
    team_id: int
    rewrites: tuple[SqlRewrite, ...]
    still_mentions_table: bool
    written: bool

    @property
    def changed(self) -> bool:
        return any(not rewrite.needs_manual_fix for rewrite in self.rewrites)

    @property
    def needs_manual_check(self) -> bool:
        return self.still_mentions_table or any(rewrite.needs_manual_fix for rewrite in self.rewrites)


class _TableReferences(TraversingVisitor):
    def __init__(self) -> None:
        self.legacy_tables: list[tuple[ast.Field, Optional[str]]] = []
        self.defines_legacy_cte = False
        self.all_chains: list[list[str | int]] = []
        self.legacy_scope_chains: list[list[str | int]] = []
        self.names_replacement = False
        self.legacy_column_aliases = False
        self.selects_by_pattern = False
        self._select_reads_legacy: list[bool] = []
        self._count_stars: set[int] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if LEGACY_TABLE in (node.ctes or {}):
            self.defines_legacy_cte = True
        if REPLACEMENT_TABLE in (node.ctes or {}):
            self.names_replacement = True
        reads_legacy = False
        join = node.select_from
        while join is not None:
            if _legacy_table(join) is not None:
                reads_legacy = True
            join = join.next_join
        self._select_reads_legacy.append(reads_legacy)
        super().visit_select_query(node)
        self._select_reads_legacy.pop()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table = _legacy_table(node)
        if table is not None:
            self.legacy_tables.append((table, node.alias))
            self.legacy_column_aliases |= bool(node.column_aliases)
        if node.alias == REPLACEMENT_TABLE or (
            isinstance(node.table, ast.Field) and node.table.chain[-1] == REPLACEMENT_TABLE
        ):
            self.names_replacement = True
        super().visit_join_expr(node)

    def visit_call(self, node: ast.Call) -> None:
        if node.name == "count" and len(node.args) == 1 and _is_star(node.args[0]):
            self._count_stars.add(id(node.args[0]))
        super().visit_call(node)

    def visit_columns_expr(self, node: ast.ColumnsExpr) -> None:
        if self._select_reads_legacy and self._select_reads_legacy[-1]:
            self.selects_by_pattern = True
        super().visit_columns_expr(node)

    def visit_field(self, node: ast.Field) -> None:
        if id(node) in self._count_stars:
            return
        self.all_chains.append(node.chain)
        if self._select_reads_legacy and self._select_reads_legacy[-1]:
            self.legacy_scope_chains.append(node.chain)


def _is_star(expr: ast.Expr) -> bool:
    return isinstance(expr, ast.Field) and expr.chain == ["*"]


def _legacy_table(join: ast.JoinExpr) -> Optional[ast.Field]:
    if isinstance(join.table, ast.Field) and join.table.chain in ([LEGACY_TABLE], ["posthog", LEGACY_TABLE]):
        return join.table
    return None


def _reads_unmapped_column(references: _TableReferences) -> bool:
    qualifiers = {LEGACY_TABLE} | {alias for _, alias in references.legacy_tables if alias}
    for chain in references.legacy_scope_chains:
        if chain[-1] not in UNMAPPED_COLUMNS:
            continue
        if len(chain) == 1 or (len(chain) == 2 and chain[0] in qualifiers):
            return True
    return False


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
    if not references.legacy_tables:
        return None

    manual_fix = SqlRewrite(before=sql, after=None)
    # A CTE of the same name shadows the table in scopes this rewrite does not model, such as later UNION branches.
    if references.defines_legacy_cte or _reads_unmapped_column(references):
        return manual_fix
    # Each of these changes what the replaced table reads: a CTE or a second table named `cohort_people`,
    # positional column aliases (the two tables order their columns differently), and `COLUMNS(...)` patterns.
    if references.names_replacement or references.legacy_column_aliases or references.selects_by_pattern:
        return manual_fix
    if any(len(chain) > 2 and chain[:2] == ["posthog", LEGACY_TABLE] for chain in references.all_chains):
        return manual_fix

    # Columns qualified with the old table name keep resolving through an alias of the same name.
    qualified_by_table_name = any(len(chain) > 1 and chain[0] == LEGACY_TABLE for chain in references.all_chains)
    rewritten = sql
    for table, alias in sorted(references.legacy_tables, key=lambda reference: reference[0].start or 0, reverse=True):
        if table.start is None or table.end is None:
            return manual_fix
        # The parser offsets can drift from the Python string, for example after a leading byte order mark.
        if sql[table.start : table.end].replace("`", "").replace('"', "") not in (
            LEGACY_TABLE,
            f"posthog.{LEGACY_TABLE}",
        ):
            return manual_fix
        replacement = REPLACEMENT_TABLE
        if alias is None and qualified_by_table_name:
            replacement = f"{REPLACEMENT_TABLE} AS {LEGACY_TABLE}"
        rewritten = rewritten[: table.start] + replacement + rewritten[table.end :]
    return SqlRewrite(before=sql, after=rewritten)


def runs_on_posthog(query: dict[str, Any]) -> bool:
    """False for a query that a direct connection or hosted Trino runs, where `cohort_membership` is another table."""
    return not query.get("connectionId") and query.get("executionTarget") in (None, "clickhouse")


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
    if rewritten.get("kind") == "HogQLQuery" and isinstance(rewritten.get("query"), str) and runs_on_posthog(rewritten):
        rewrite = rewrite_hogql(rewritten["query"])
        if rewrite is not None:
            rewrites.append(rewrite)
            if rewrite.after is not None:
                rewritten["query"] = rewrite.after
    return rewritten, rewrites


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def mentions_legacy_table(value: Any) -> bool:
    return any(LEFTOVER_MENTION.search(text) for text in _strings(value))


def rewrite_saved_rows(
    queryset: QuerySet[Any],
    field: str,
    source: SavedQuerySource,
    rewrite_value: Callable[[Any], tuple[Any, list[SqlRewrite]]],
    apply: bool,
    extra_updates: Callable[[], dict[str, Any]] = dict,
) -> list[SavedQueryRewrite]:
    """Rewrites `field` on each row of `queryset` that mentions the table, writing only when `apply` is set."""
    matching = queryset.annotate(field_text=Cast(field, TextField())).filter(field_text__contains=LEGACY_TABLE)
    results: list[SavedQueryRewrite] = []
    for pk, team_id, value in matching.values_list("pk", "team_id", field):
        new_value, rewrites = rewrite_value(value)
        still_mentions_table = mentions_legacy_table(new_value)
        if not rewrites and not still_mentions_table:
            continue
        changed = any(not rewrite.needs_manual_fix for rewrite in rewrites)
        written = False
        if apply and changed:
            # The filter on the value read keeps an edit saved since then, which the next run picks up.
            written = (
                queryset.model._base_manager.filter(pk=pk, **{field: value}).update(
                    **{field: new_value, **extra_updates()}
                )
                == 1
            )
        results.append(
            SavedQueryRewrite(
                source=source,
                pk=str(pk),
                team_id=team_id,
                rewrites=tuple(rewrites),
                still_mentions_table=still_mentions_table,
                written=written,
            )
        )
    return results
