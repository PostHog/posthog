from pydantic import Field

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders
from posthog.hogql.visitor import TraversingVisitor

from ...facade.enums import CheckType, SubjectType
from ..contracts import CheckPlan, SubjectRef
from ..errors import CheckConfigError
from ..metric_query import bind_metric_query
from ..query_scope import referenced_table_names as query_table_names
from ..spec import CheckConfig, CheckTypeSpec


def parse_failing_rows_query(query: str) -> ast.SelectQuery | ast.SelectSetQuery:
    """Parse user HogQL into the SELECT whose rows are the failures.

    A UNION of selects is as good as one: the compiler aggregates over whatever this returns, so the
    failure set can be assembled from several branches.
    """
    parsed = parse_custom_sql_query(query)

    found = find_placeholders(parsed)
    if found.has_filters or found.placeholder_fields or found.placeholder_expressions:
        raise CheckConfigError("A custom_sql check cannot use {placeholders} -- nothing supplies them.")

    shadowing = _AliasShadowFinder()
    shadowing.visit(parsed)
    if shadowing.name is not None:
        raise CheckConfigError(
            f"The alias {shadowing.name} has the same name as a column it is computed from. "
            f"ClickHouse reads every other {shadowing.name} in the query as the alias, not the column, "
            "so the check fails or compares the wrong value. Rename the alias."
        )
    return parsed


class _BareColumnNames(TraversingVisitor):
    """Bare column names read within one SELECT scope, leaving out the nodes in `skip`."""

    def __init__(self, root: ast.Expr, skip: tuple[ast.Expr, ...] = ()) -> None:
        self.names: set[str] = set()
        self._root = root
        self._skip = {id(node) for node in skip}
        self._bound: list[set[str]] = []

    def visit(self, node: ast.AST | None) -> None:
        if node is not None and id(node) in self._skip:
            return
        super().visit(node)

    def visit_field(self, node: ast.Field) -> None:
        # A dotted chain such as properties.order_id reads a property or a joined table, not the column
        # the alias hides, so only a bare name can clash.
        if len(node.chain) == 1 and not any(node.chain[0] in bound for bound in self._bound):
            self.names.add(str(node.chain[0]))

    def visit_lambda(self, node: ast.Lambda) -> None:
        self._bound.append(set(node.args))
        super().visit_lambda(node)
        self._bound.pop()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A subquery has its own scope, so its columns cannot clash with an alias in this one.
        if node is self._root:
            super().visit_select_query(node)


def _bare_column_names(root: ast.Expr, skip: tuple[ast.Expr, ...] = ()) -> set[str]:
    finder = _BareColumnNames(root, skip)
    finder.visit(root)
    return finder.names


class _AliasShadowFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.name: str | None = None

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if self.name is None:
            self.name = self._shadowed_alias(node)
        super().visit_select_query(node)

    def _shadowed_alias(self, node: ast.SelectQuery) -> str | None:
        items = node.select or []
        # One pass per SELECT: collect each item's names once, so the cost stays linear in the query size.
        read_by_item = [_bare_column_names(item) for item in items]
        read_by_clauses = _bare_column_names(node, skip=tuple(items))
        read_elsewhere: dict[str, int] = {}
        for names in [*read_by_item, read_by_clauses]:
            for name in names:
                read_elsewhere[name] = read_elsewhere.get(name, 0) + 1

        for item, own_names in zip(items, read_by_item):
            # `x AS x` and `t.x AS x` only rename the column, so nothing changes when ClickHouse reads x as the alias.
            if not isinstance(item, ast.Alias) or isinstance(item.expr, ast.Field):
                continue
            # ClickHouse resolves the alias's own expression against the column, so the alias only
            # hides the column from the rest of the same SELECT.
            if item.alias in own_names and read_elsewhere.get(item.alias, 0) > 1:
                return item.alias
        return None


def parse_custom_sql_query(query: str) -> ast.SelectQuery | ast.SelectSetQuery:
    try:
        return parse_select(query.rstrip(";").strip())
    except ExposedHogQLError as err:
        raise CheckConfigError(f"Could not parse the custom query: {err}")
    except Exception:
        raise CheckConfigError("Could not parse the custom query.")


def build_failing_rows(subject: SubjectRef | None, config: "CustomSqlConfig") -> ast.SelectQuery | ast.SelectSetQuery:
    if subject is None or subject.subject_type != SubjectType.METRIC:
        return parse_failing_rows_query(config.query)
    if subject.metric_definition is None:
        raise CheckConfigError("Metric checks require a live HogQL definition.")
    return bind_metric_query(config.query, subject.metric_definition)


class CustomSqlConfig(CheckConfig):
    lookback_hours: None = Field(default=None, exclude=True, json_schema_extra={"readOnly": True})
    query: str = Field(
        min_length=1,
        description=(
            "HogQL SELECT returning one row per failure. Passing means it returns nothing. "
            "Metric checks must use {metric} once as a relation."
        ),
    )


class CustomSqlSpec(CheckTypeSpec):
    """A user-written HogQL SELECT whose returned rows are the failures.

    No extra sandboxing: HogQL is already team-scoped and read-only, and the query is wrapped in a
    count so rows never leave ClickHouse. Placeholders are rejected because nothing supplies them.

    Nothing forces the query to read the check's own subject -- the subject decides when the check
    runs and where its result is reported, not what the SQL may touch. A check whose query reads
    elsewhere is therefore possible, and reports against the wrong table.
    """

    type_name = CheckType.CUSTOM_SQL
    config_model = CustomSqlConfig
    requires_column = False
    subject_types = frozenset({SubjectType.TABLE, SubjectType.VIEW, SubjectType.METRIC, SubjectType.POSTHOG_TABLE})
    reads_beyond_subject = True
    description = "Fails on every row the custom HogQL SELECT returns. Metric checks query the {metric} relation."

    def referenced_table_names(self, config: CheckConfig, subject: SubjectRef | None = None) -> list[str]:
        assert isinstance(config, CustomSqlConfig)
        return query_table_names(build_failing_rows(subject, config))

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> CheckPlan:
        assert isinstance(config, CustomSqlConfig)
        failing_rows = build_failing_rows(subject, config)
        query_table_names(failing_rows)
        return CheckPlan(failing_rows=failing_rows)


SPEC = CustomSqlSpec()
