from datetime import UTC, datetime, timedelta
from functools import cached_property

from posthog.schema import (
    BookActivityFirstsQuery,
    BookActivityFirstsQueryResponse,
    BookActivityFirstsResult,
    BookActivityMatrixEmptyReason,
    BookActivityMatrixFirstUse,
    BookActivityMatrixRow,
    BookActivityPersonFirstUse,
    CachedBookActivityFirstsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.customer_analytics.backend.constants import BOOK_ACTIVITY_PEOPLE_QUERY_STATUS_LABEL_PREFIX
from products.customer_analytics.backend.hogql_queries.book_activity_base import (
    BookActivityQueryRunner,
    day_key,
    events_for_products,
    events_where,
    in_values,
    person_label,
    product_events,
    validated_product_keys,
)
from products.customer_analytics.backend.logic.posthog_product_usage import POSTHOG_PRODUCTS

MAX_FIRST_USE_ROWS = 49999
FIRST_USE_CACHE_TTL = timedelta(hours=24)


class BookActivityFirstsQueryRunner(BookActivityQueryRunner[BookActivityFirstsQueryResponse]):
    query: BookActivityFirstsQuery
    cached_response: CachedBookActivityFirstsQueryResponse

    def query_status_labels(self) -> list[str]:
        user_id = self.user.id if isinstance(self.user, User) else "anonymous"
        return [*super().query_status_labels(), f"{BOOK_ACTIVITY_PEOPLE_QUERY_STATUS_LABEL_PREFIX}{user_id}"]

    def validate_query_runner_access(self, user: User) -> bool:
        super().validate_query_runner_access(user)
        UserAccessControl(user=user, team=self.team).assert_access_level_for_resource("person", "viewer")
        return True

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
        group_type_index = self.team.customer_analytics_config.account_group_type_index
        accounts = self._book_accounts[: self._row_limit]
        if group_type_index is None or not accounts:
            return ast.SelectQuery.empty()
        qualified = product_events(
            group_type_index,
            events_where(
                group_type_index,
                [account.external_id or "" for account in accounts],
                upper=datetime.now(UTC),
                events=events_for_products(keys),
            ),
            extra=[
                parse_expr("coalesce(person.properties.email, '') AS email"),
                parse_expr("coalesce(person.properties.name, '') AS name"),
            ],
        )
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
                    value=MAX_FIRST_USE_ROWS + 1 if people else len(accounts) * len(POSTHOG_PRODUCTS)
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
        rows = [
            BookActivityMatrixRow(key=str(account.id), label=account.name, externalId=account.external_id or "")
            for account in accounts
        ]
        group_type_index = self.team.customer_analytics_config.account_group_type_index
        reason = (
            BookActivityMatrixEmptyReason.NO_GROUP_TYPE
            if group_type_index is None
            else BookActivityMatrixEmptyReason.EMPTY_BOOK
            if not accounts
            else None
        )
        results = BookActivityFirstsResult(
            rows=rows, people=[], accounts=[], truncated=self._accounts_were_dropped, emptyReason=reason
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
        # Account dates need an independent aggregate because the person cap can omit whole accounts.
        account_response = self._execute("BookActivityFirstsAccounts", self._firsts_query(people=False))
        results.accounts = [
            BookActivityMatrixFirstUse(row=account_by_key[account_key], series=product, date=day_key(first))
            for account_key, product, first in account_response.results or []
            if account_key in account_by_key
        ]
        response.hogql = people_response.hogql
        response.timings = self.timings.to_list()
        return response
