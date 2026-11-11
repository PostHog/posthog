from posthog.schema import (
    AccountActivityMatrixColumn,
    AccountActivityMatrixEmptyReason,
    AccountTopPage,
    AccountTopPagesQuery,
    AccountTopPagesQueryResponse,
    AccountTopPagesResult,
    BookActivityMatrixProduct,
    CachedAccountTopPagesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from products.customer_analytics.backend.hogql_queries.account_scoped_activity_base import (
    AccountScopedActivityQueryRunner,
)
from products.customer_analytics.backend.hogql_queries.book_activity_base import (
    section_product_expr,
    validated_product_keys,
)
from products.customer_analytics.backend.logic.posthog_product_usage import POSTHOG_PRODUCTS

PAGE_LIMIT = 200
PATH_MAX_CHARS = 200
TITLE_MAX_CHARS = 300
PAGEVIEW_EVENT = "$pageview"

# Long, generated paths would each become their own row, so the path is cut before grouping.
PAGE_PATH = f"substring(replaceRegexpOne(coalesce(toString(properties.$pathname), ''), '^/project/[^/]+', ''), 1, {PATH_MAX_CHARS})"


class AccountTopPagesQueryRunner(AccountScopedActivityQueryRunner[AccountTopPagesQueryResponse]):
    """Runs 1 ClickHouse query over the account's pageviews."""

    query: AccountTopPagesQuery
    cached_response: CachedAccountTopPagesQueryResponse

    def to_query(self) -> ast.SelectQuery:
        external_id, group_type_index = self._group_identity()
        if not external_id or group_type_index is None:
            return ast.SelectQuery.empty()
        return self._pages_query(external_id, group_type_index)

    def _calculate(self) -> AccountTopPagesQueryResponse:
        validated_product_keys([self.query.productKey] if self.query.productKey else [])
        columns = self._columns()
        external_id, group_type_index = self._group_identity()
        if not external_id:
            return self._response(columns, [], empty_reason=AccountActivityMatrixEmptyReason.NO_EXTERNAL_ID)
        if group_type_index is None:
            return self._response(columns, [], empty_reason=AccountActivityMatrixEmptyReason.NO_GROUP_TYPE)
        rows = self._execute("AccountTopPagesQuery", self._pages_query(external_id, group_type_index)).results or []
        pages = [
            AccountTopPage(
                path=str(path) or "/",
                title=str(title or ""),
                product=str(product or ""),
                views=int(views),
                people=int(people),
                activeDays=int(active_days),
                lastViewed=last_viewed.isoformat() if hasattr(last_viewed, "isoformat") else str(last_viewed),
            )
            for path, title, product, views, people, active_days, last_viewed in rows
        ]
        return self._response(columns, pages, truncated=len(pages) >= PAGE_LIMIT)

    def _response(
        self,
        columns: list[AccountActivityMatrixColumn],
        pages: list[AccountTopPage],
        *,
        truncated: bool = False,
        empty_reason: AccountActivityMatrixEmptyReason | None = None,
    ) -> AccountTopPagesQueryResponse:
        return AccountTopPagesQueryResponse(
            results=AccountTopPagesResult(
                columns=columns,
                pages=pages,
                products=[
                    BookActivityMatrixProduct(key=product.key, label=product.label) for product in POSTHOG_PRODUCTS
                ],
                truncated=truncated,
                emptyReason=empty_reason,
            ),
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )

    def _pages_query(self, external_id: str, group_type_index: int) -> ast.SelectQuery:
        path = parse_expr(PAGE_PATH)
        product = section_product_expr(
            ast.Call(
                name="arrayElement",
                args=[
                    ast.Call(name="splitByChar", args=[ast.Constant(value="/"), parse_expr(PAGE_PATH)]),
                    ast.Constant(value=2),
                ],
            )
        )
        where: ast.Expr = self._where(external_id, group_type_index, [PAGEVIEW_EVENT])
        query = parse_select(
            f"""
            SELECT path, title, product, views, people, active_days, last_viewed
            FROM (
                SELECT {{path}} AS path,
                    substring(argMax(coalesce(toString(properties.title), ''), timestamp), 1, {TITLE_MAX_CHARS}) AS title,
                    any({{product}}) AS product,
                    count() AS views,
                    uniq(person_id) AS people,
                    uniq(toDate(timestamp)) AS active_days,
                    max(timestamp) AS last_viewed
                FROM events
                WHERE {{where}}
                GROUP BY path
            )
            WHERE {{product_filter}}
            ORDER BY views DESC, path ASC
            LIMIT {PAGE_LIMIT}
            """,
            placeholders={
                "path": path,
                "product": product,
                "where": where,
                "product_filter": parse_expr(
                    "product = {key}", placeholders={"key": ast.Constant(value=self.query.productKey)}
                )
                if self.query.productKey
                else ast.Constant(value=True),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
