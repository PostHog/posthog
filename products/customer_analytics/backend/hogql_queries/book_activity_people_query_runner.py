from functools import cached_property

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    BookActivityPeopleQuery,
    BookActivityPeopleQueryResponse,
    BookActivityPeopleResult,
    BookActivityPerson,
    BookActivityPersonAction,
    BookActivityPersonPath,
    CachedBookActivityPeopleQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.customer_analytics.backend.hogql_queries.book_activity_base import (
    BookActivityRangeQueryRunner,
    day_key,
    events_for_products,
    events_where,
    in_values,
    person_label,
    product_events,
    validated_product_keys,
)
from products.customer_analytics.backend.logic.posthog_product_usage import PAGE_EVENTS

DEFAULT_PEOPLE_LIMIT = 3
MAX_PEOPLE_ROWS = 20000
TOP_PATHS = 5


class BookActivityPeopleQueryRunner(BookActivityRangeQueryRunner[BookActivityPeopleQueryResponse]):
    query: BookActivityPeopleQuery
    cached_response: CachedBookActivityPeopleQueryResponse

    requires_person_access = True

    @cached_property
    def _product_keys(self) -> list[str]:
        if self.query.peopleLimit is not None and not 1 <= self.query.peopleLimit <= 50:
            raise ValidationError("Choose between 1 and 50 people per cell.")
        keys = validated_product_keys(self.query.productKeys)
        if self.query.allPeople and (len(self.query.accountIds or []) != 1 or len(keys) != 1):
            raise ValidationError("Choose one account and one product to show all people.")
        return keys

    def to_query(self) -> ast.SelectQuery:
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
                lower=self._date_range.date_from(),
                upper=self._date_range.date_to(),
                events=events_for_products(keys),
            ),
            period=self._period_expr(),
            extra=[
                parse_expr("event"),
                parse_expr("coalesce(person.properties.email, '') AS email"),
                parse_expr("coalesce(person.properties.name, '') AS name"),
                parse_expr(
                    "if(event IN {pages}, toFloat(properties.$prev_pageview_duration), 0) AS engaged",
                    placeholders={"pages": ast.Tuple(exprs=[ast.Constant(value=event) for event in PAGE_EVENTS])},
                ),
                parse_expr(
                    "if(event IN {pages}, replaceRegexpOne(toString(properties.$prev_pageview_pathname), '^/project/[^/]+', ''), '') AS path",
                    placeholders={"pages": ast.Tuple(exprs=[ast.Constant(value=event) for event in PAGE_EVENTS])},
                ),
            ],
        )
        query = parse_select(
            """
            SELECT account_key, period, product, person_id, email, name,
                engaged_seconds, action_count, actions,
                arraySlice(arraySort(x -> (-x.2, x.1), arrayZip(paths.1, paths.2)), 1, {top_paths}) AS top_paths,
                person_rank
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY account_key, product, period
                    ORDER BY engaged_seconds + action_count DESC, person_id ASC
                ) AS person_rank
                FROM (
                    SELECT account_key, period, product, person_id,
                        argMax(email, timestamp) AS email, argMax(name, timestamp) AS name,
                        sum(engaged) AS engaged_seconds,
                        countIf(event NOT IN {pages}) AS action_count,
                        sumMap([event], [if(event NOT IN {pages}, 1, 0)]) AS actions,
                        sumMap([path], [engaged]) AS paths
                    FROM {qualified}
                    WHERE {products}
                    GROUP BY account_key, period, product, person_id
                )
            )
            WHERE person_rank <= {people_limit}
            ORDER BY account_key, product, period, person_rank
            LIMIT {row_limit}
            """,
            placeholders={
                "qualified": qualified,
                "pages": ast.Tuple(exprs=[ast.Constant(value=event) for event in PAGE_EVENTS]),
                "products": in_values(ast.Field(chain=["product"]), keys) if keys else parse_expr("product != ''"),
                "people_limit": ast.Constant(
                    value=MAX_PEOPLE_ROWS + 1
                    if self.query.allPeople
                    else self.query.peopleLimit or DEFAULT_PEOPLE_LIMIT
                ),
                "row_limit": ast.Constant(value=MAX_PEOPLE_ROWS + 1),
                "top_paths": ast.Constant(value=TOP_PATHS),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _calculate(self) -> BookActivityPeopleQueryResponse:
        if not isinstance(self.user, User):
            raise UserAccessControlError("account", "viewer")
        _ = self._product_keys
        columns = self._columns()
        accounts = self._book_accounts[: self._row_limit]
        reason = self._empty_reason
        results = BookActivityPeopleResult(
            rows=self._rows, columns=columns, people=[], truncated=self._accounts_were_dropped, emptyReason=reason
        )
        response = BookActivityPeopleQueryResponse(
            results=results, timings=self.timings.to_list(), modifiers=self.modifiers
        )
        if reason:
            return response
        account_by_key = {account.external_id: str(account.id) for account in accounts}
        query_response = self._execute("BookActivityPeopleQuery", self.to_query())
        raw = query_response.results or []
        results.truncated = results.truncated or len(raw) > MAX_PEOPLE_ROWS
        for account_key, period, product, person_id, email, name, engaged, action_count, actions, paths, rank in raw[
            :MAX_PEOPLE_ROWS
        ]:
            if account_key not in account_by_key:
                continue
            results.people.append(
                BookActivityPerson(
                    row=account_by_key[account_key],
                    column=day_key(period),
                    series=product,
                    personId=str(person_id),
                    label=person_label(email, name, str(person_id)),
                    rank=int(rank),
                    engagedSeconds=int(engaged),
                    actionCount=int(action_count),
                    actions=[
                        BookActivityPersonAction(event=event, count=int(count))
                        for event, count in sorted(zip(*actions), key=lambda item: (-item[1], item[0]))
                        if count
                    ],
                    topPaths=[
                        BookActivityPersonPath(path=path, seconds=int(seconds))
                        for path, seconds in paths
                        if path and seconds
                    ][:TOP_PATHS],
                )
            )
        response.hogql = query_response.hogql
        response.timings = self.timings.to_list()
        return response
