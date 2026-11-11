from datetime import date, datetime, timedelta
from functools import cached_property
from typing import Generic

from posthog.schema import AccountActivityMatrixColumn, AccountAgentActivityQuery, AccountTopPagesQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.query_runner import AR
from posthog.models.user import User
from posthog.week_start_day import WeekStartDay

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.customer_analytics.backend.constants import ACCOUNT_ACTIVITY_MATRIX_QUERY_STATUS_LABEL_PREFIX
from products.customer_analytics.backend.hogql_queries.activity_base import ActivityQueryRunner, activity_columns
from products.customer_analytics.backend.hogql_queries.book_activity_base import in_values
from products.customer_analytics.backend.logic.account_activity_access import get_account_activity_account
from products.customer_analytics.backend.logic.posthog_product_usage import STAFF_EMAIL_PATTERN
from products.customer_analytics.backend.models import Account

DEFAULT_WEEKS = 8
MAX_WEEKS = 26


class AccountScopedActivityQueryRunner(ActivityQueryRunner[AR], Generic[AR]):
    """One account's events over whole weeks, behind the same access checks as the account activity matrix."""

    query: AccountAgentActivityQuery | AccountTopPagesQuery

    def validate_query_runner_access(self, user: User) -> bool:
        get_account_activity_account(team=self.team, user=user, account_id=self.query.accountId)
        return True

    def get_cache_key_variant(self) -> str:
        try:
            get_account_activity_account(team=self.team, user=self.user, account_id=self.query.accountId)
        except UserAccessControlError:
            return f"{super().get_cache_key_variant()}_denied"
        return super().get_cache_key_variant()

    def query_status_labels(self) -> list[str]:
        return [f"{ACCOUNT_ACTIVITY_MATRIX_QUERY_STATUS_LABEL_PREFIX}{self.query.accountId}"]

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        try:
            payload["account_external_id"] = self._account.external_id
        except UserAccessControlError:
            payload["account_external_id"] = None
        return payload

    @cached_property
    def _account(self) -> Account:
        return get_account_activity_account(team=self.team, user=self.user, account_id=self.query.accountId)

    def _group_identity(self) -> tuple[str | None, int | None]:
        return self._account.external_id or None, self.team.customer_analytics_config.account_group_type_index

    @cached_property
    def _week_starts(self) -> list[date]:
        weeks = max(1, min(self.query.weeks or DEFAULT_WEEKS, MAX_WEEKS))
        today = datetime.now(tz=self.team.timezone_info).date()
        first_weekday = 0 if self._week_start_day == WeekStartDay.MONDAY else 6
        current = today - timedelta(days=(today.weekday() - first_weekday) % 7)
        return [current - timedelta(weeks=offset) for offset in reversed(range(weeks))]

    def _columns(self) -> list[AccountActivityMatrixColumn]:
        return activity_columns(self._week_starts, self._week_starts[-1])

    def _lower(self) -> datetime:
        return datetime.combine(self._week_starts[0], datetime.min.time(), tzinfo=self.team.timezone_info)

    def _week_expr(self) -> ast.Expr:
        return ast.Call(
            name="toStartOfWeek",
            args=[ast.Field(chain=["timestamp"]), ast.Constant(value=int(self._week_start_day.clickhouse_mode))],
        )

    def _where(self, external_id: str, group_type_index: int, events: list[str]) -> ast.Expr:
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[f"$group_{group_type_index}"]),
                    right=ast.Constant(value=external_id),
                ),
                in_values(ast.Field(chain=["event"]), events),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=self._lower()),
                ),
                parse_expr(
                    "NOT coalesce(person.properties.email, '') ILIKE {staff}",
                    placeholders={"staff": ast.Constant(value=STAFF_EMAIL_PATTERN)},
                ),
            ]
        )
