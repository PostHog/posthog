from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from functools import cached_property
from uuid import UUID

from django.db.models import QuerySet

from rest_framework.exceptions import ValidationError

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
    IntervalType,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled
from posthog.week_start_day import WeekStartDay

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.customer_analytics.backend.constants import (
    BOOK_ACTIVITY_MATRIX_QUERY_STATUS_LABEL_PREFIX,
    CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG,
)
from products.customer_analytics.backend.logic.posthog_product_usage import (
    ENGAGED_MAX_SECONDS,
    ENGAGED_SECONDS,
    PAGE_EVENTS,
    POSTHOG_PRODUCTS,
    PRODUCT_GROUPINGS,
    REPLAY_WATCH_EVENT,
    REPLAY_WATCH_MS,
    STAFF_EMAIL_PATTERN,
)
from products.customer_analytics.backend.models import Account, AccountRelationship

DEFAULT_ROW_LIMIT = 50
MAX_ROW_LIMIT = 200
MAX_ACCOUNT_IDS = 200
MAX_DAILY_RANGE = timedelta(days=93)
MAX_COMBINATION_ROWS = 50000
FIRST_USE_FLOOR = datetime(2020, 1, 1, tzinfo=UTC)


class BookActivityMatrixQueryRunner(AnalyticsQueryRunner[BookActivityMatrixQueryResponse]):
    query: BookActivityMatrixQuery
    cached_response: CachedBookActivityMatrixQueryResponse

    def validate_query_runner_access(self, user: User) -> bool:
        UserAccessControl(user=user, team=self.team).assert_access_level_for_resource("account", "viewer")
        # Runs before the cache lookup, so turning the flag off also stops cached results.
        if not posthog_feature_flag_enabled(
            CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG,
            user.distinct_id or str(user.uuid),
            organization_id=self.team.organization_id,
            team_id=self.team.id,
        ):
            raise UserAccessControlError("account", "viewer")
        return True

    def get_cache_key_variant(self) -> str:
        if not isinstance(self.user, User):
            return f"{super().get_cache_key_variant()}_denied"
        return super().get_cache_key_variant()

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        payload["book_accounts"] = [(str(account.id), account.external_id) for account in self._book_accounts]
        return payload

    def query_status_labels(self) -> list[str]:
        user_id = self.user.id if isinstance(self.user, User) else "anonymous"
        return [f"{BOOK_ACTIVITY_MATRIX_QUERY_STATUS_LABEL_PREFIX}{user_id}"]

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
        truncated = len(self._book_accounts) > self._row_limit or len(self.query.accountIds or []) > MAX_ACCOUNT_IDS
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
        tag_queries(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY)
        response = execute_hogql_query(
            query_type="BookActivityMatrixQuery",
            query=self._combinations_query(group_type_index, list(account_by_key)),
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            workload=Workload.ONLINE,
        )
        results = response.results or []
        combinations = [
            BookActivityMatrixCombination(
                row=account_by_key[str(account_key)],
                column=_day_key(period),
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

    @cached_property
    def _book_accounts(self) -> list[Account]:
        if not isinstance(self.user, User):
            return []
        candidates = self._candidate_accounts()
        if candidates is None:
            return []
        visible = UserAccessControl(user=self.user, team=self.team).filter_queryset_by_access_level(
            candidates.filter(ignored_at__isnull=True, external_id__isnull=False).exclude(external_id=""),
            resource="account",
        )
        return list(visible.order_by("name", "id").only("id", "name", "external_id")[: self._row_limit + 1])

    def _candidate_accounts(self) -> QuerySet[Account] | None:
        accounts = Account.objects.for_team(self.team.id)
        if self.query.accountIds is not None:
            account_ids = [UUID(value) for value in self.query.accountIds[:MAX_ACCOUNT_IDS] if _is_uuid(value)]
            return accounts.filter(id__in=account_ids)
        if self.query.relationshipDefinitionId is None or not _is_uuid(self.query.relationshipDefinitionId):
            return None
        relationships = AccountRelationship.objects.for_team(self.team.id).filter(
            definition_id=UUID(self.query.relationshipDefinitionId), ended_at__isnull=True
        )
        if self.query.userId is not None:
            relationships = relationships.filter(user_id=self.query.userId)
        return accounts.filter(id__in=relationships.values("account_id"))

    @cached_property
    def _row_limit(self) -> int:
        return max(1, min(self.query.rowLimit or DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT))

    @cached_property
    def _date_range(self) -> QueryDateRange:
        date_range = QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType(self.query.interval.value),
            now=datetime.now(tz=self.team.timezone_info),
        )
        if self.query.interval.value == "day" and date_range.date_to() - date_range.date_from() > MAX_DAILY_RANGE:
            raise ValidationError("Daily buckets cover at most 3 months. Choose Week or Month for a longer range.")
        return date_range

    @cached_property
    def _week_start_day(self) -> WeekStartDay:
        return WeekStartDay(self.team.week_start_day or WeekStartDay.SUNDAY)

    def _bucket(self, day: date) -> date:
        interval = self.query.interval.value
        if interval == "month":
            return day.replace(day=1)
        if interval == "week":
            first_weekday = 0 if self._week_start_day == WeekStartDay.MONDAY else 6
            return day - timedelta(days=(day.weekday() - first_weekday) % 7)
        return day

    def _next(self, bucket: date) -> date:
        interval = self.query.interval.value
        if interval == "month":
            return (bucket.replace(day=28) + timedelta(days=4)).replace(day=1)
        if interval == "week":
            return bucket + timedelta(weeks=1)
        return bucket + timedelta(days=1)

    def _columns(self) -> list[AccountActivityMatrixColumn]:
        date_from = self._date_range.date_from().astimezone(self.team.timezone_info).date()
        date_to = self._date_range.date_to().astimezone(self.team.timezone_info).date()
        current = self._bucket(datetime.now(tz=self.team.timezone_info).date())
        keys: list[date] = []
        bucket = self._bucket(date_from)
        while bucket <= date_to:
            keys.append(bucket)
            bucket = self._next(bucket)
        return [AccountActivityMatrixColumn(key=key.isoformat(), partial=key == current) for key in keys]

    def _period_expr(self) -> ast.Expr:
        timestamp = ast.Field(chain=["timestamp"])
        interval = self.query.interval.value
        if interval == "month":
            return ast.Call(name="toStartOfMonth", args=[timestamp])
        if interval == "week":
            return ast.Call(
                name="toStartOfWeek", args=[timestamp, ast.Constant(value=int(self._week_start_day.clickhouse_mode))]
            )
        return ast.Call(name="toStartOfDay", args=[timestamp])

    def _events_where(self, group_type_index: int, account_keys: list[str], *, bounded: bool) -> ast.Expr:
        lower = self._date_range.date_from() if bounded else FIRST_USE_FLOOR
        exprs: list[ast.Expr] = [
            _in(ast.Field(chain=[f"$group_{group_type_index}"]), account_keys),
            _in(ast.Field(chain=["event"]), _all_events()),
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=lower)
            ),
            ast.Not(
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike,
                    left=ast.Call(
                        name="coalesce",
                        args=[ast.Field(chain=["person", "properties", "email"]), ast.Constant(value="")],
                    ),
                    right=ast.Constant(value=STAFF_EMAIL_PATTERN),
                )
            ),
        ]
        if bounded:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=self._date_range.date_to()),
                )
            )
        return ast.And(exprs=exprs)

    def _product_events(self, group_type_index: int, account_keys: list[str], *, bounded: bool) -> ast.SelectQuery:
        select: list[ast.Expr] = [
            ast.Alias(alias="account_key", expr=ast.Field(chain=[f"$group_{group_type_index}"])),
            ast.Field(chain=["person_id"]),
            ast.Field(chain=["timestamp"]),
            ast.Alias(alias="product", expr=_product_expr()),
        ]
        if bounded:
            select.insert(1, ast.Alias(alias="period", expr=self._period_expr()))
        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._events_where(group_type_index, account_keys, bounded=bounded),
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
            select_from=ast.JoinExpr(table=self._product_events(group_type_index, account_keys, bounded=True)),
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
            select_from=ast.JoinExpr(table=self._product_events(group_type_index, list(account_by_key), bounded=False)),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq, left=ast.Field(chain=["product"]), right=ast.Constant(value="")
            ),
            group_by=[ast.Field(chain=["account_key"]), ast.Field(chain=["product"])],
            limit=ast.Constant(value=len(account_by_key) * len(POSTHOG_PRODUCTS)),
        )
        response = execute_hogql_query(
            query_type="BookActivityMatrixFirstUse",
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            workload=Workload.ONLINE,
        )
        return [
            BookActivityMatrixFirstUse(row=account_by_key[str(account_key)], series=str(product), date=_day_key(first))
            for account_key, product, first in response.results or []
            if str(account_key) in account_by_key
        ]


def _in(left: ast.Expr, values: list[str] | tuple[str, ...]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=left,
        right=ast.Tuple(exprs=[ast.Constant(value=value) for value in values]),
    )


def _all_events() -> list[str]:
    events = {event for product in POSTHOG_PRODUCTS for event in product.actions}
    return sorted(events | set(PAGE_EVENTS) | {REPLAY_WATCH_EVENT})


def _between(value: ast.Expr, low: int, high: int) -> ast.Expr:
    return ast.And(
        exprs=[
            ast.CompareOperation(op=ast.CompareOperationOp.GtEq, left=value, right=ast.Constant(value=low)),
            ast.CompareOperation(op=ast.CompareOperationOp.LtEq, left=value, right=ast.Constant(value=high)),
        ]
    )


def _product_expr() -> ast.Expr:
    section = ast.Call(
        name="arrayElement",
        args=[
            ast.Call(
                name="splitByChar",
                args=[
                    ast.Constant(value="/"),
                    ast.Call(
                        name="coalesce",
                        args=[
                            ast.Call(
                                name="toString", args=[ast.Field(chain=["properties", "$prev_pageview_pathname"])]
                            ),
                            ast.Constant(value=""),
                        ],
                    ),
                ],
            ),
            ast.Constant(value=4),
        ],
    )
    duration = ast.Call(name="toFloat", args=[ast.Field(chain=["properties", "$prev_pageview_duration"])])
    play_time = ast.Call(name="toFloat", args=[ast.Field(chain=["properties", "play_time_ms"])])
    page_product: list[ast.Expr] = []
    for product in POSTHOG_PRODUCTS:
        if product.sections:
            page_product.extend([_in(section, product.sections), ast.Constant(value=product.key)])
    page_product.append(ast.Constant(value=""))
    branches: list[ast.Expr] = [
        ast.And(
            exprs=[
                _in(ast.Field(chain=["event"]), PAGE_EVENTS),
                _between(duration, ENGAGED_SECONDS, ENGAGED_MAX_SECONDS),
            ]
        ),
        ast.Call(name="multiIf", args=page_product),
        ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=REPLAY_WATCH_EVENT),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq, left=play_time, right=ast.Constant(value=REPLAY_WATCH_MS)
                ),
            ]
        ),
        ast.Constant(value="replay"),
    ]
    for product in POSTHOG_PRODUCTS:
        if product.actions:
            branches.extend([_in(ast.Field(chain=["event"]), product.actions), ast.Constant(value=product.key)])
    branches.append(ast.Constant(value=""))
    return ast.Call(name="multiIf", args=branches)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _day_key(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


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
