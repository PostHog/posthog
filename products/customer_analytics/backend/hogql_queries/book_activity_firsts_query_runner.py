from datetime import UTC, datetime, timedelta
from functools import cached_property

from posthog.schema import (
    BookActivityFirstsQuery,
    BookActivityFirstsQueryResponse,
    BookActivityFirstsResult,
    BookActivityMatrixFirstUse,
    BookActivityPersonFirstUse,
    CachedBookActivityFirstsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.customer_analytics.backend.hogql_queries.book_activity_base import (
    BookActivityQueryRunner,
    day_key,
    in_values,
    person_label,
    validated_product_keys,
)
from products.customer_analytics.backend.logic.posthog_product_usage import POSTHOG_PRODUCTS

MAX_FIRST_USE_ROWS = 49999
FIRST_USE_CACHE_TTL = timedelta(hours=24)


class BookActivityFirstsQueryRunner(BookActivityQueryRunner[BookActivityFirstsQueryResponse]):
    query: BookActivityFirstsQuery
    cached_response: CachedBookActivityFirstsQueryResponse

    requires_person_access = True

    def cache_target_age(self, last_refresh: datetime | None, lazy: bool = False) -> datetime | None:
        return last_refresh + FIRST_USE_CACHE_TTL if last_refresh else None

    def _is_stale(self, last_refresh: datetime | None, lazy: bool = False) -> bool:
        return last_refresh is None or datetime.now(UTC) > last_refresh + FIRST_USE_CACHE_TTL

    @cached_property
    def _product_keys(self) -> list[str]:
        return validated_product_keys(self.query.productKeys)

    def to_query(self) -> ast.SelectQuery:
        return self._firsts_query(people=True)

    def _firsts_query(self, *, people: bool) -> ast.SelectQuery:
        keys = self._product_keys
        if self._empty_reason:
            return ast.SelectQuery.empty()
        qualified = self._person_product_events(keys, upper=datetime.now(UTC))
        if people:
            sql = """
                SELECT account_key, product, person_id, argMax(email, timestamp), argMax(name, timestamp),
                    toDate(min(timestamp)) AS first_day
                FROM {qualified} WHERE {products}
                GROUP BY account_key, product, person_id
                ORDER BY account_key, product, first_day, person_id LIMIT {row_limit}
            """
        else:
            sql = """
                SELECT account_key, product, toDate(min(timestamp))
                FROM {qualified} WHERE {products}
                GROUP BY account_key, product
                ORDER BY account_key, product LIMIT {row_limit}
            """
        query = parse_select(
            sql,
            placeholders={
                "qualified": qualified,
                "products": in_values(ast.Field(chain=["product"]), keys) if keys else parse_expr("product != ''"),
                "row_limit": ast.Constant(
                    value=MAX_FIRST_USE_ROWS + 1
                    if people
                    else len(self._book_accounts[: self._row_limit]) * len(POSTHOG_PRODUCTS)
                ),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _calculate(self) -> BookActivityFirstsQueryResponse:
        if not isinstance(self.user, User):
            raise UserAccessControlError("account", "viewer")
        _ = self._product_keys
        accounts = self._book_accounts[: self._row_limit]
        reason = self._empty_reason
        results = BookActivityFirstsResult(
            rows=self._rows, people=[], accounts=[], truncated=self._accounts_were_dropped, emptyReason=reason
        )
        response = BookActivityFirstsQueryResponse(
            results=results, timings=self.timings.to_list(), modifiers=self.modifiers
        )
        if reason:
            return response
        account_by_key = {account.external_id: str(account.id) for account in accounts}
        people_response = self._execute("BookActivityFirstsQuery", self.to_query())
        people = people_response.results or []
        results.truncated = results.truncated or len(people) > MAX_FIRST_USE_ROWS
        results.people = [
            BookActivityPersonFirstUse(
                row=account_by_key[account_key],
                series=product,
                personId=str(person_id),
                label=person_label(email, name, str(person_id)),
                date=day_key(first),
            )
            for account_key, product, person_id, email, name, first in people[:MAX_FIRST_USE_ROWS]
            if account_key in account_by_key
        ]
        if len(people) > MAX_FIRST_USE_ROWS:
            # The person cap can omit whole accounts, so truncated results need an independent aggregate.
            account_response = self._execute("BookActivityFirstsAccounts", self._firsts_query(people=False))
            results.accounts = [
                BookActivityMatrixFirstUse(row=account_by_key[account_key], series=product, date=day_key(first))
                for account_key, product, first in account_response.results or []
                if account_key in account_by_key
            ]
        else:
            account_firsts: dict[tuple[str, str], str] = {}
            for person in results.people:
                key = (person.row, person.series)
                account_firsts[key] = min(account_firsts.get(key, person.date), person.date)
            results.accounts = [
                BookActivityMatrixFirstUse(row=row, series=product, date=first)
                for (row, product), first in account_firsts.items()
            ]
        response.hogql = people_response.hogql
        response.timings = self.timings.to_list()
        return response
