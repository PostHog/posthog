from posthog.schema import AccountsQuery, AccountsQueryResponse, CachedAccountsQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

DEFAULT_COLUMNS = ("id", "name", "external_id", "created_at")

DEFAULT_ORDER_BY = "created_at DESC"


def _normalize_order_clause(raw: str) -> str:
    """Allow Django-style `-col` shorthand alongside native HogQL `col DESC`."""
    stripped = raw.strip()
    if stripped.startswith("-"):
        return f"{stripped[1:].strip()} DESC"
    return stripped


ROLE_FIELDS = {
    "csm": "csm",
    "accountExecutive": "account_executive",
    "accountOwner": "account_owner",
}


class AccountsQueryRunner(AnalyticsQueryRunner[AccountsQueryResponse]):
    query: AccountsQuery
    cached_response: CachedAccountsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.query.select:
            seen: set[str] = set()
            self.columns: list[str] = []
            self._select_exprs: list[ast.Expr] = []
            for col in self.query.select:
                expr = parse_expr(col)
                column_name = expr.alias if isinstance(expr, ast.Alias) else col
                if column_name in seen:
                    continue
                seen.add(column_name)
                self.columns.append(column_name)
                self._select_exprs.append(expr)
        else:
            self.columns = list(DEFAULT_COLUMNS)
            self._select_exprs = [parse_expr(col) for col in self.columns]

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context,
            limit=self.query.limit,
            offset=self.query.offset,
        )

    def to_query(self) -> ast.SelectQuery:
        where_exprs: list[ast.Expr] = []

        if self.query.search and self.query.search.strip():
            pattern = f"%{self.query.search.strip()}%"
            where_exprs.append(
                parse_expr(
                    "name ILIKE {pattern} OR external_id ILIKE {pattern}",
                    {"pattern": ast.Constant(value=pattern)},
                )
            )

        if self.query.tagNames:
            where_exprs.append(self._tag_filter_expr(self.query.tagNames))

        for query_field, json_key in ROLE_FIELDS.items():
            role_value = getattr(self.query, query_field, None)
            role_expr = self._role_filter_expr(json_key, role_value)
            if role_expr is not None:
                where_exprs.append(role_expr)

        if self.query.allRolesUnassigned:
            for json_key in ROLE_FIELDS.values():
                where_exprs.append(self._role_id_isnull(json_key))

        order_clauses = self.query.orderBy or [DEFAULT_ORDER_BY]

        return ast.SelectQuery(
            select=self._select_exprs,
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["system", "accounts"]),
                alias="accounts",
            ),
            where=ast.And(exprs=where_exprs) if where_exprs else None,
            order_by=[parse_order_expr(_normalize_order_clause(c), timings=self.timings) for c in order_clauses],
        )

    def _tag_filter_expr(self, tag_names: list[str]) -> ast.Expr:
        subquery = parse_select(
            """
            SELECT ti.account_id
            FROM system._account_tagged_items AS ti
            INNER JOIN system.tags AS t ON t.id = ti.tag_id
            WHERE t.name IN {tag_names}
            """,
            {"tag_names": ast.Constant(value=list(tag_names))},
        )
        return parse_expr("id IN {subquery}", {"subquery": subquery})

    def _role_filter_expr(self, json_key: str, value: object) -> ast.Expr | None:
        if value is None:
            return None
        if value == "unassigned":
            return self._role_id_isnull(json_key)
        try:
            user_id = int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return None
        return parse_expr(
            "JSONExtract(properties, {role_key}, 'id', 'Nullable(Int64)') = {user_id}",
            {
                "role_key": ast.Constant(value=json_key),
                "user_id": ast.Constant(value=user_id),
            },
        )

    def _role_id_isnull(self, json_key: str) -> ast.Expr:
        return parse_expr(
            "isNull(JSONExtract(properties, {role_key}, 'id', 'Nullable(Int64)'))",
            {"role_key": ast.Constant(value=json_key)},
        )

    def _calculate(self) -> AccountsQueryResponse:
        response = self.paginator.execute_hogql_query(
            query_type="AccountsQuery",
            query=self.to_query(),
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        return AccountsQueryResponse(
            kind="AccountsQuery",
            columns=list(self.columns),
            results=self.paginator.results,
            types=[t for _, t in response.types] if response.types else [],
            hogql=response.hogql or "",
            timings=response.timings,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
