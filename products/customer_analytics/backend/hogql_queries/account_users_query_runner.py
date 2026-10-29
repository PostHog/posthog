from posthog.schema import AccountUsersQuery, HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.customer_analytics.backend.constants import ACCOUNT_USERS_QUERY_STATUS_LABEL_PREFIX
from products.customer_analytics.backend.logic.account_member_search import (
    get_account_users_organization_id,
    list_organization_member_distinct_ids,
)


class AccountUsersQueryRunner(AnalyticsQueryRunner[HogQLQueryResponse]):
    """Persons who use an account. Runs only as an `ActorsQuery` source, which hydrates the persons.

    The person set comes from the PostHog Cloud organization whose ID is the account's external ID,
    so it only works in PostHog's own project.
    """

    query: AccountUsersQuery

    def validate_query_runner_access(self, user: User) -> bool:
        get_account_users_organization_id(team=self.team, user=user, account_id=self.query.accountId)
        return True

    def get_cache_key_variant(self) -> str:
        # Anonymous share-link viewers and cache-only reads skip `validate_query_runner_access`. A
        # separate key for them misses staff results, and a fresh run then fails the access check.
        try:
            get_account_users_organization_id(team=self.team, user=self.user, account_id=self.query.accountId)
        except UserAccessControlError:
            return f"{super().get_cache_key_variant()}_denied"
        return super().get_cache_key_variant()

    def query_status_labels(self) -> list[str]:
        return [f"{ACCOUNT_USERS_QUERY_STATUS_LABEL_PREFIX}{self.query.accountId}"]

    def _list_distinct_ids(self) -> tuple[str, ...]:
        organization_id = get_account_users_organization_id(
            team=self.team, user=self.user, account_id=self.query.accountId
        )
        if organization_id is None:
            return ()
        # Narrowed by the access check above, which rejects any principal that is not a User.
        assert isinstance(self.user, User)
        return list_organization_member_distinct_ids(team=self.team, user=self.user, organization_id=organization_id)

    def to_query(self) -> ast.SelectQuery:
        distinct_ids = self._list_distinct_ids()
        condition: ast.Expr = (
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["distinct_id"]),
                right=ast.Tuple(exprs=[ast.Constant(value=distinct_id) for distinct_id in distinct_ids]),
            )
            if distinct_ids
            else ast.Constant(value=False)
        )
        query = parse_select(
            "SELECT DISTINCT person_id FROM person_distinct_ids WHERE {condition}",
            placeholders={"condition": condition},
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def to_actors_query(self) -> ast.SelectQuery:
        return self.to_query()

    def _calculate(self) -> HogQLQueryResponse:
        return execute_hogql_query(
            query_type="AccountUsersQuery",
            query=self.to_query(),
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
