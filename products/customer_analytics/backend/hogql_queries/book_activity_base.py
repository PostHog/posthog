from datetime import UTC, date, datetime, timedelta
from functools import cached_property
from typing import Generic
from uuid import UUID

from django.db.models import QuerySet

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AccountActivityMatrixColumn,
    BookActivityFirstsQuery,
    BookActivityMatrixEmptyReason,
    BookActivityMatrixQuery,
    BookActivityMatrixRow,
    BookActivityPeopleQuery,
    IntervalType,
)

from posthog.hogql import ast

from posthog.hogql_queries.query_runner import AR
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.user import User
from posthog.week_start_day import WeekStartDay

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.constants import (
    BOOK_ACTIVITY_ACCOUNTS_QUERY_STATUS_LABEL_PREFIX,
    BOOK_ACTIVITY_MATRIX_QUERY_STATUS_LABEL_PREFIX,
    BOOK_ACTIVITY_PEOPLE_QUERY_STATUS_LABEL_PREFIX,
)
from products.customer_analytics.backend.hogql_queries.activity_base import (
    ActivityQueryRunner,
    activity_columns,
    is_uuid,
)
from products.customer_analytics.backend.logic.book_activity_access import validate_book_activity_query_access
from products.customer_analytics.backend.logic.posthog_product_usage import (
    ENGAGED_MAX_SECONDS,
    ENGAGED_SECONDS,
    PAGE_EVENTS,
    POSTHOG_PRODUCTS,
    REPLAY_WATCH_EVENT,
    REPLAY_WATCH_MS,
    STAFF_EMAIL_PATTERN,
)
from products.customer_analytics.backend.models import Account, AccountRelationship

MAX_ACCOUNT_IDS = 200
MAX_DAILY_RANGE = timedelta(days=93)
MAX_PERIODS = 104
FIRST_USE_FLOOR = datetime(2020, 1, 1, tzinfo=UTC)


class BookActivityQueryRunner(ActivityQueryRunner[AR], Generic[AR]):
    """Who may read which accounts of a book. Every book activity query shares these checks."""

    query: BookActivityMatrixQuery | BookActivityPeopleQuery | BookActivityFirstsQuery
    requires_person_access = False

    def validate_query_runner_access(self, user: User) -> bool:
        validate_book_activity_query_access(self.team, user)
        if self.requires_person_access:
            UserAccessControl(user=user, team=self.team).assert_access_level_for_resource("person", "viewer")
        return True

    def _on_user_changed(self) -> None:
        super()._on_user_changed()
        self.__dict__.pop("_book_accounts", None)

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
        account_ids = ",".join(str(account.id) for account in self._book_accounts[: self._row_limit])
        labels = [
            f"{BOOK_ACTIVITY_MATRIX_QUERY_STATUS_LABEL_PREFIX}{user_id}",
            f"{BOOK_ACTIVITY_ACCOUNTS_QUERY_STATUS_LABEL_PREFIX}{account_ids}",
        ]
        if self.requires_person_access:
            labels.append(f"{BOOK_ACTIVITY_PEOPLE_QUERY_STATUS_LABEL_PREFIX}{user_id}")
        return labels

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
            account_ids = [UUID(value) for value in self.query.accountIds[:MAX_ACCOUNT_IDS] if is_uuid(value)]
            return accounts.filter(id__in=account_ids)
        if self.query.relationshipDefinitionId is None or not is_uuid(self.query.relationshipDefinitionId):
            return None
        relationships = AccountRelationship.objects.for_team(self.team.id).filter(
            definition_id=UUID(self.query.relationshipDefinitionId), ended_at__isnull=True
        )
        if self.query.userId is not None:
            relationships = relationships.filter(user_id=self.query.userId)
        return accounts.filter(id__in=relationships.values("account_id"))

    @property
    def _rows(self) -> list[BookActivityMatrixRow]:
        return [
            BookActivityMatrixRow(key=str(account.id), label=account.name, externalId=account.external_id or "")
            for account in self._book_accounts[: self._row_limit]
        ]

    @property
    def _empty_reason(self) -> BookActivityMatrixEmptyReason | None:
        if self.team.customer_analytics_config.account_group_type_index is None:
            return BookActivityMatrixEmptyReason.NO_GROUP_TYPE
        if not self._book_accounts:
            return BookActivityMatrixEmptyReason.EMPTY_BOOK
        return None

    @property
    def _accounts_were_dropped(self) -> bool:
        return len(self._book_accounts) > self._row_limit or len(self.query.accountIds or []) > MAX_ACCOUNT_IDS


class BookActivityRangeQueryRunner(BookActivityQueryRunner[AR], Generic[AR]):
    """A book activity query split into day, week or month buckets, in the team's timezone."""

    query: BookActivityMatrixQuery | BookActivityPeopleQuery

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
        first_bucket = self._bucket(date_range.date_from().astimezone(self.team.timezone_info).date())
        last_bucket = self._bucket(date_range.date_to().astimezone(self.team.timezone_info).date())
        if self.query.interval.value == "month":
            periods = (last_bucket.year - first_bucket.year) * 12 + last_bucket.month - first_bucket.month + 1
        else:
            bucket_days = 7 if self.query.interval.value == "week" else 1
            periods = (last_bucket - first_bucket).days // bucket_days + 1
        if periods > MAX_PERIODS:
            raise ValidationError(f"Book activity supports at most {MAX_PERIODS} periods. Choose a shorter range.")
        return date_range

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
        return activity_columns(keys, current)

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


def events_where(
    group_type_index: int,
    account_keys: list[str],
    *,
    lower: datetime | None = None,
    upper: datetime | None = None,
    events: list[str] | None = None,
) -> ast.Expr:
    exprs: list[ast.Expr] = [
        in_values(ast.Field(chain=[f"$group_{group_type_index}"]), account_keys),
        in_values(ast.Field(chain=["event"]), events if events is not None else all_events()),
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
    if lower is not None:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=lower)
            )
        )
    if upper is not None:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=upper),
            )
        )
    return ast.And(exprs=exprs)


def product_events(
    group_type_index: int, where: ast.Expr, *, period: ast.Expr | None = None, extra: list[ast.Expr] | None = None
) -> ast.SelectQuery:
    select: list[ast.Expr] = [
        ast.Alias(alias="account_key", expr=ast.Field(chain=[f"$group_{group_type_index}"])),
        ast.Field(chain=["person_id"]),
        ast.Field(chain=["timestamp"]),
        ast.Alias(alias="product", expr=product_expr()),
    ]
    if period is not None:
        select.insert(1, ast.Alias(alias="period", expr=period))
    return ast.SelectQuery(
        select=[*select, *(extra or [])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=where,
    )


def in_values(left: ast.Expr, values: list[str] | tuple[str, ...]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=left,
        right=ast.Tuple(exprs=[ast.Constant(value=value) for value in values]),
    )


def all_events() -> list[str]:
    events = {event for product in POSTHOG_PRODUCTS for event in product.actions}
    return sorted(events | set(PAGE_EVENTS) | {REPLAY_WATCH_EVENT})


def events_for_products(product_keys: list[str]) -> list[str]:
    """Narrows the scan. The rule stays in `product_expr`, so a narrower list never changes who qualifies."""
    if not product_keys:
        return all_events()
    events = {event for product in POSTHOG_PRODUCTS if product.key in product_keys for event in product.actions}
    if "replay" in product_keys:
        events.add(REPLAY_WATCH_EVENT)
    return sorted(events | set(PAGE_EVENTS))


def validated_product_keys(product_keys: list[str] | None) -> list[str]:
    keys = list(dict.fromkeys(product_keys or []))
    known = {product.key for product in POSTHOG_PRODUCTS}
    unknown = [key for key in keys if key not in known]
    if unknown:
        raise ValidationError(f"Unknown products: {', '.join(unknown)}.")
    return keys


def _between(value: ast.Expr, low: int, high: int) -> ast.Expr:
    return ast.And(
        exprs=[
            ast.CompareOperation(op=ast.CompareOperationOp.GtEq, left=value, right=ast.Constant(value=low)),
            ast.CompareOperation(op=ast.CompareOperationOp.LtEq, left=value, right=ast.Constant(value=high)),
        ]
    )


def product_expr() -> ast.Expr:
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
            page_product.extend([in_values(section, product.sections), ast.Constant(value=product.key)])
    page_product.append(ast.Constant(value=""))
    branches: list[ast.Expr] = [
        ast.And(
            exprs=[
                in_values(ast.Field(chain=["event"]), PAGE_EVENTS),
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
            branches.extend([in_values(ast.Field(chain=["event"]), product.actions), ast.Constant(value=product.key)])
    branches.append(ast.Constant(value=""))
    return ast.Call(name="multiIf", args=branches)


def person_label(email: object, name: object, person_id: str) -> str:
    return str(email or name or f"User {person_id[:8]}")


def day_key(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
