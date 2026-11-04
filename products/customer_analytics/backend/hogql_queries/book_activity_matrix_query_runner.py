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
        rows = [
            BookActivityMatrixRow(key=str(account.id), label=account.name, externalId=account.external_id or "")
            for account in accounts
        ]
        if group_type_index is None:
            return self._response(rows, columns, [], [], None, truncated, BookActivityMatrixEmptyReason.NO_GROUP_TYPE)
        if not accounts:
            return self._response(rows, columns, [], [], None, truncated, BookActivityMatrixEmptyReason.EMPTY_BOOK)

        account_by_key = {account.external_id: str(account.id) for account in accounts if account.external_id}
        response = self._execute(
            "BookActivityMatrixQuery", self._combinations_query(group_type_index, list(account_by_key))
        )
        results = response.results or []
        combinations = [
            BookActivityMatrixCombination(
                row=account_by_key[str(account_key)],
                column=day_key(period),
                mask=int(mask),
                users=int(users),
            )
            for account_key, period, mask, users in results
            if str(account_key) in account_by_key and int(mask)
        ]
        first_use = self._first_use(group_type_index, account_by_key) if self.query.includeFirstUse else None
        return self._response(
            rows,
            columns,
            combinations,
            _users_per_product(combinations),
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
        mask: ast.Expr = ast.Constant(value=0)
        for index, product in enumerate(POSTHOG_PRODUCTS):
            uses = ast.Call(
                name="max",
                args=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["product"]),
                        right=ast.Constant(value=product.key),
                    )
                ],
            )
            mask = ast.ArithmeticOperation(
                op=ast.ArithmeticOperationOp.Add,
                left=mask,
                right=ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Mult, left=uses, right=ast.Constant(value=1 << index)
                ),
            )
        per_person = ast.SelectQuery(
            select=[
                ast.Field(chain=["account_key"]),
                ast.Field(chain=["period"]),
                ast.Field(chain=["person_id"]),
                ast.Alias(alias="mask", expr=mask),
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


def _users_per_product(combinations: list[BookActivityMatrixCombination]) -> list[BookActivityMatrixCell]:
    totals: dict[tuple[str, str, str], int] = defaultdict(int)
    for combination in combinations:
        for index, product in enumerate(POSTHOG_PRODUCTS):
            if combination.mask & (1 << index):
                totals[(combination.row, combination.column, product.key)] += combination.users
    return [
        BookActivityMatrixCell(row=row, column=column, series=series, users=users)
        for (row, column, series), users in totals.items()
    ]
