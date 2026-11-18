import re
from collections.abc import Iterator
from typing import Any, Optional

from django.db.models import QuerySet, TextField
from django.db.models.functions import Cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.schema_enums import ExecutionTarget

LEGACY_TABLE = "cohort_membership"
REPLACEMENT_TABLE = "cohort_people"
# `cohort_people` has neither column, and `*` over it returns a different column list.
UNMAPPED_COLUMNS = {"status", "last_updated", "*"}
LEFTOVER_MENTION = re.compile(rf"\b{LEGACY_TABLE}\b")


@frozen
class SqlRewrite:
    before: str
    after: Optional[str]

    @property
    def needs_manual_fix(self) -> bool:
        return self.after is None


@frozen
class SavedQueryRewrite:
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
    aliases = {alias for _, alias in references.legacy_tables if alias}
    for chain in references.legacy_scope_chains:
        if chain[-1] not in UNMAPPED_COLUMNS:
            continue
        if len(chain) == 1 or (len(chain) == 2 and chain[0] in aliases):
            return True
    return False


def _needs_manual_fix(references: _TableReferences) -> bool:
    # A CTE of the same name shadows the table in scopes this rewrite does not model, such as later UNION branches.
    if references.defines_legacy_cte or _reads_unmapped_column(references):
        return True
    # Each of these changes what the replaced table reads: a CTE or a second table named `cohort_people`,
    # positional column aliases (the two tables order their columns differently), and `COLUMNS(...)` patterns.
    if references.names_replacement or references.legacy_column_aliases or references.selects_by_pattern:
        return True
    # A rename would break `posthog.cohort_membership` and columns qualified with the table name. No saved query uses
    # either form, so the command leaves them for a manual fix.
    if any(len(table.chain) > 1 for table, _ in references.legacy_tables):
        return True
    return any(len(chain) > 1 and LEGACY_TABLE in chain[:2] for chain in references.all_chains)


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
    if _needs_manual_fix(references):
        return manual_fix

    rewritten = sql
    for table, _alias in sorted(references.legacy_tables, key=lambda reference: reference[0].start or 0, reverse=True):
        if table.start is None or table.end is None:
            return manual_fix
        # The parser offsets can drift from the Python string, for example after a leading byte order mark.
        if sql[table.start : table.end].replace("`", "").replace('"', "") != LEGACY_TABLE:
            return manual_fix
        rewritten = rewritten[: table.start] + REPLACEMENT_TABLE + rewritten[table.end :]
    return SqlRewrite(before=sql, after=rewritten)


def _runs_on_posthog(node: dict[str, Any]) -> bool:
    # A direct connection or hosted Trino runs the SQL elsewhere, where `cohort_membership` is another table.
    # Every other target runs on ClickHouse, as in the HogQL query runner.
    return not node.get("connectionId") and node.get("executionTarget") != ExecutionTarget.MANAGED_TRINO


def rewrite_query_nodes(value: Any) -> tuple[Any, list[SqlRewrite]]:
    """Rewrites every HogQLQuery node that PostHog runs, nested anywhere in a saved query."""
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
    sql = rewritten.get("query")
    if rewritten.get("kind") == "HogQLQuery" and isinstance(sql, str) and _runs_on_posthog(rewritten):
        rewrite = rewrite_hogql(sql)
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


def rewrite_saved_rows(queryset: QuerySet[Any], apply: bool) -> list[SavedQueryRewrite]:
    """Rewrites the `query` of each row of `queryset` that mentions the table, writing only when `apply` is set."""
    matching = queryset.annotate(query_text=Cast("query", TextField())).filter(query_text__contains=LEGACY_TABLE)
    results: list[SavedQueryRewrite] = []
    for pk, team_id, value in matching.values_list("pk", "team_id", "query"):
        new_value, rewrites = rewrite_query_nodes(value)
        still_mentions_table = mentions_legacy_table(new_value)
        if not rewrites and not still_mentions_table:
            continue
        changed = any(not rewrite.needs_manual_fix for rewrite in rewrites)
        written = False
        if apply and changed:
            # The filter on the value read keeps an edit saved since then, which the next run picks up.
            written = queryset.model._base_manager.filter(pk=pk, query=value).update(query=new_value) == 1
        results.append(
            SavedQueryRewrite(
                pk=str(pk),
                team_id=team_id,
                rewrites=tuple(rewrites),
                still_mentions_table=still_mentions_table,
                written=written,
            )
        )
    return results
