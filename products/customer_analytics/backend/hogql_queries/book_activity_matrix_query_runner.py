from collections import defaultdict

from posthog.schema import (
    AccountActivityMatrixColumn,
    BookActivityMatrixCell,
    BookActivityMatrixCombination,
    BookActivityMatrixEmptyReason,
    BookActivityMatrixFirstUse,
    BookActivityMatrixGroup,
    BookActivityMatrixGrouping,
    BookActivityMatrixProduct,
    BookActivityMatrixQuery,
    BookActivityMatrixQueryResponse,
    BookActivityMatrixResult,
    BookActivityMatrixRow,
    CachedBookActivityMatrixQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.customer_analytics.backend.hogql_queries.book_activity_base import (
    FIRST_USE_FLOOR,
    BookActivityRangeQueryRunner,
    day_key,
    events_where,
    product_events,
)
from products.customer_analytics.backend.logic.posthog_product_usage import POSTHOG_PRODUCTS, PRODUCT_GROUPINGS

MAX_COMBINATION_ROWS = 50000


class BookActivityMatrixQueryRunner(BookActivityRangeQueryRunner[BookActivityMatrixQueryResponse]):
    query: BookActivityMatrixQuery
    cached_response: CachedBookActivityMatrixQueryResponse

    def to_query(self) -> ast.SelectQuery:
        group_type_index = self.team.customer_analytics_config.account_group_type_index
        accounts = self._book_accounts[: self._row_limit]
        if group_type_index is None or not accounts:
            return ast.SelectQuery.empty()
        return self._combinations_query(group_type_index, [account.external_id or "" for account in accounts])

    def _calculate(self) -> BookActivityMatrixQueryResponse:
        if not isinstance(self.user, User):
            raise UserAccessControlError("account", "viewer")
        columns = self._columns()
        accounts = self._book_accounts[: self._row_limit]
        truncated = self._accounts_were_dropped
        group_type_index = self.team.customer_analytics_config.account_group_type_index
        rows = self._rows
        reason = self._empty_reason
        if reason:
            return self._response(rows, columns, [], [], None, truncated, reason)
        assert group_type_index is not None

        account_by_key = {account.external_id: str(account.id) for account in accounts if account.external_id}
        response = self._execute(
            "BookActivityMatrixQuery", self._combinations_query(group_type_index, list(account_by_key))
        )
        results = response.results or []
        book_results = [
            (account_by_key[str(account_key)], day_key(period), int(mask), int(users), ui_users, agent_users)
            for account_key, period, mask, users, ui_users, agent_users in results
            if str(account_key) in account_by_key and int(mask)
        ]
        combinations = [
            BookActivityMatrixCombination(row=row, column=column, mask=mask, users=users)
            for row, column, mask, users, _ui_users, _agent_users in book_results
        ]
        first_use = self._first_use(group_type_index, account_by_key) if self.query.includeFirstUse else None
        return self._response(
            rows,
            columns,
            combinations,
            _users_per_product(book_results),
            first_use,
            truncated or len(results) >= MAX_COMBINATION_ROWS,
            None,
            response.hogql,
        )

    def _response(
        self,
        rows: list[BookActivityMatrixRow],
        columns: list[AccountActivityMatrixColumn],
        combinations: list[BookActivityMatrixCombination],
        data: list[BookActivityMatrixCell],
        first_use: list[BookActivityMatrixFirstUse] | None,
        truncated: bool,
        empty_reason: BookActivityMatrixEmptyReason | None,
        hogql: str | None = None,
    ) -> BookActivityMatrixQueryResponse:
        return BookActivityMatrixQueryResponse(
            results=BookActivityMatrixResult(
                rows=rows,
                columns=columns,
                groupings=[
                    BookActivityMatrixGrouping(
                        key=grouping.key,
                        label=grouping.label,
                        groups=[
                            BookActivityMatrixGroup(key=group.key, label=group.label, items=list(group.products))
                            for group in grouping.groups
                        ],
                    )
                    for grouping in PRODUCT_GROUPINGS
                ],
                series=[
                    BookActivityMatrixProduct(key=product.key, label=product.label) for product in POSTHOG_PRODUCTS
                ],
                data=data,
                combinations=combinations,
                firstUse=first_use,
                truncated=truncated,
                emptyReason=empty_reason,
            ),
            hogql=hogql,
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )

    def _combinations_query(self, group_type_index: int, account_keys: list[str]) -> ast.SelectQuery:
        mask = _product_mask()
        ui_mask = _product_mask("ui")
        agent_mask = _product_mask("agent")
        per_person = ast.SelectQuery(
            select=[
                ast.Field(chain=["account_key"]),
                ast.Field(chain=["period"]),
                ast.Field(chain=["person_id"]),
                ast.Alias(alias="mask", expr=mask),
                ast.Alias(alias="ui_mask", expr=ui_mask),
                ast.Alias(alias="agent_mask", expr=agent_mask),
            ],
            select_from=ast.JoinExpr(
                table=product_events(
                    group_type_index,
                    events_where(
                        group_type_index,
                        account_keys,
                        lower=self._date_range.date_from(),
                        upper=self._date_range.date_to(),
                    ),
                    period=self._period_expr(),
                )
            ),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq, left=ast.Field(chain=["product"]), right=ast.Constant(value="")
            ),
            group_by=[ast.Field(chain=["account_key"]), ast.Field(chain=["period"]), ast.Field(chain=["person_id"])],
        )
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["account_key"]),
                ast.Field(chain=["period"]),
                ast.Field(chain=["mask"]),
                ast.Alias(alias="users", expr=ast.Call(name="count", args=[])),
                ast.Alias(alias="ui_users", expr=_users_per_bit("ui_mask")),
                ast.Alias(alias="agent_users", expr=_users_per_bit("agent_mask")),
            ],
            select_from=ast.JoinExpr(table=per_person),
            group_by=[ast.Field(chain=["account_key"]), ast.Field(chain=["period"]), ast.Field(chain=["mask"])],
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["account_key"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["period"]), order="ASC"),
            ],
            limit=ast.Constant(value=MAX_COMBINATION_ROWS),
        )

    def _first_use(self, group_type_index: int, account_by_key: dict[str, str]) -> list[BookActivityMatrixFirstUse]:
        query = ast.SelectQuery(
            select=[
                ast.Field(chain=["account_key"]),
                ast.Field(chain=["product"]),
                ast.Alias(alias="first_used_at", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
            ],
            select_from=ast.JoinExpr(
                table=product_events(
                    group_type_index, events_where(group_type_index, list(account_by_key), lower=FIRST_USE_FLOOR)
                )
            ),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq, left=ast.Field(chain=["product"]), right=ast.Constant(value="")
            ),
            group_by=[ast.Field(chain=["account_key"]), ast.Field(chain=["product"])],
            limit=ast.Constant(value=len(account_by_key) * len(POSTHOG_PRODUCTS)),
        )
        response = self._execute("BookActivityMatrixFirstUse", query)
        return [
            BookActivityMatrixFirstUse(row=account_by_key[str(account_key)], series=str(product), date=day_key(first))
            for account_key, product, first in response.results or []
            if str(account_key) in account_by_key
        ]


def _product_mask(channel: str | None = None) -> ast.Expr:
    """One bit per product the person used in the period, optionally through one channel only."""
    mask: ast.Expr = ast.Constant(value=0)
    for index, product in enumerate(POSTHOG_PRODUCTS):
        condition: ast.Expr = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["product"]), right=ast.Constant(value=product.key)
        )
        if channel is not None:
            condition = ast.And(
                exprs=[
                    condition,
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["channel"]),
                        right=ast.Constant(value=channel),
                    ),
                ]
            )
        mask = ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Add,
            left=mask,
            right=ast.ArithmeticOperation(
                op=ast.ArithmeticOperationOp.Mult,
                left=ast.Call(name="max", args=[condition]),
                right=ast.Constant(value=1 << index),
            ),
        )
    return mask


def _users_per_bit(mask: str) -> ast.Expr:
    """People per product index in a combination who have that product's bit set in `mask`."""
    return parse_expr(
        "sumForEach(arrayMap(index -> toInt(bitTest({mask}, index)), range({product_count})))",
        placeholders={
            "mask": ast.Field(chain=[mask]),
            "product_count": ast.Constant(value=len(POSTHOG_PRODUCTS)),
        },
    )


def _users_per_product(
    book_results: list[tuple[str, str, int, int, list[int], list[int]]],
) -> list[BookActivityMatrixCell]:
    totals: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for row, column, mask, users, ui_users, agent_users in book_results:
        for index, product in enumerate(POSTHOG_PRODUCTS):
            if not mask & (1 << index):
                continue
            counts = totals[(row, column, product.key)]
            counts[0] += users
            counts[1] += int(ui_users[index])
            counts[2] += int(agent_users[index])
    return [
        BookActivityMatrixCell(
            row=row, column=column, series=series, users=users, uiUsers=ui_users, agentUsers=agent_users
        )
        for (row, column, series), (users, ui_users, agent_users) in totals.items()
    ]
