import json
from hashlib import sha256

from posthog.schema import HogQLPropertyFilter

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.actor_strategies import person_email_property_keys
from posthog.models import Team, User
from posthog.permissions import posthog_feature_flag_enabled

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.facade.api import get_accessible_account_id, get_account

ACCOUNT_PERSONS_FLAG = "customer-analytics-account-persons-api"


class AccountPersonsReader:
    @classmethod
    def create(
        cls,
        *,
        team: Team,
        user: User | None,
        account_id: str,
        user_access_control: UserAccessControl | None = None,
    ) -> "AccountPersonsReader | None":
        if (
            not isinstance(user, User)
            or not user.is_active
            or not posthog_feature_flag_enabled(
                ACCOUNT_PERSONS_FLAG, str(user.distinct_id), organization_id=team.organization_id, team_id=team.pk
            )
        ):
            return None
        access = user_access_control or UserAccessControl(user=user, team=team)
        if not access.check_access_level_for_resource("account", "viewer"):
            return None
        if get_accessible_account_id(team.pk, account_id, access) is None:
            return None
        account = get_account(team.pk, account_id=account_id)
        group_type_index = team.customer_analytics_config.account_group_type_index
        if account is None or group_type_index is None or group_type_index not in range(5):
            return None
        return cls(
            team=team,
            user=user,
            group_type_index=group_type_index,
            group_key=account.external_id,
            account_id=account_id,
        )

    def __init__(
        self, *, team: Team, user: User, group_type_index: int, group_key: str | None, account_id: str = ""
    ) -> None:
        self.account_id = account_id
        self.team = team
        self.user = user
        self.group_type_index = group_type_index
        self.group_key = group_key

    def get_access_key(self) -> str:
        restrictions = get_restricted_properties_with_group_type_index_for_team(user=self.user, team_id=self.team.pk)
        access = UserAccessControl(user=self.user, team=self.team)
        payload = {
            "user_id": self.user.pk,
            "group_type_index": self.group_type_index,
            "group_key": self.group_key,
            "properties": sorted(
                (item.property_type, item.group_type_index if item.group_type_index is not None else -1, item.name)
                for item in restrictions
            ),
            "blocked_objects": {scope: sorted(ids) for scope, ids in access.blocked_resource_ids_by_scope.items()},
            "allowed_objects": {scope: sorted(ids) for scope, ids in access.allowlisted_resource_ids_by_scope.items()},
            "blocked_resources": sorted(access.blocked_resources),
        }
        return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def get_source_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT pdi.person_id AS person_id,
                groupUniqArray(101)(membership.distinct_id) AS distinct_ids,
                min(membership.first_seen) AS account_first_seen,
                max(membership.last_seen) AS account_last_seen
            FROM posthog.person_group_membership AS membership
            INNER JOIN (
                SELECT argMax(person_id, version) AS person_id, distinct_id
                FROM raw_person_distinct_ids
                WHERE distinct_id IN (
                    SELECT distinct_id FROM posthog.person_group_membership
                    WHERE group_type_index = {group_type_index} AND group_key = {group_key}
                )
                GROUP BY distinct_id
                HAVING argMax(is_deleted, version) = 0
            ) AS pdi ON membership.distinct_id = pdi.distinct_id
            WHERE membership.group_type_index = {group_type_index} AND membership.group_key = {group_key}
            GROUP BY pdi.person_id
            """,
            placeholders={
                "group_type_index": ast.Constant(value=self.group_type_index),
                "group_key": ast.Constant(value=self.group_key),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        assert query.select_from is not None and query.select_from.next_join is not None
        query.select_from.next_join.join_type = "GLOBAL INNER JOIN"
        return query

    def get_display_name(self, restricted_properties: frozenset[str]) -> ast.Expr:
        property_keys = self.team.person_display_name_properties or ["email", "name", "username"]
        return ast.Call(
            name="coalesce",
            args=[
                *[
                    ast.Call(
                        name="nullIf",
                        args=[
                            ast.Call(name="toString", args=[ast.Field(chain=["properties", key])]),
                            ast.Constant(value=""),
                        ],
                    )
                    for key in property_keys
                    if key not in restricted_properties
                ],
                ast.Call(name="toString", args=[ast.Field(chain=["persons", "id"])]),
            ],
        )

    def get_search_filter(self, search: str, restricted_properties: frozenset[str]) -> HogQLPropertyFilter:
        expressions: list[ast.Expr] = [ast.Call(name="toString", args=[ast.Field(chain=["persons", "id"])])]
        expressions.extend(
            ast.Call(name="toString", args=[ast.Field(chain=["properties", key])])
            for key in dict.fromkeys([*person_email_property_keys(self.team), "name"])
            if key not in restricted_properties
        )
        condition = ast.Or(
            exprs=[
                *[
                    ast.CompareOperation(
                        left=expr,
                        op=ast.CompareOperationOp.ILike,
                        right=ast.Constant(value=f"%{search}%"),
                    )
                    for expr in expressions
                ],
                ast.CompareOperation(
                    left=ast.Field(chain=["persons", "id"]),
                    op=ast.CompareOperationOp.In,
                    right=parse_select(
                        """
                        SELECT argMax(person_id, version) AS person_id
                        FROM raw_person_distinct_ids
                        WHERE distinct_id IN (
                            SELECT distinct_id FROM posthog.person_group_membership
                            WHERE group_type_index = {group_type_index}
                                AND group_key = {group_key}
                                AND ilike(distinct_id, {search})
                        )
                        GROUP BY distinct_id
                        HAVING argMax(is_deleted, version) = 0
                        """,
                        placeholders={
                            "group_type_index": ast.Constant(value=self.group_type_index),
                            "group_key": ast.Constant(value=self.group_key),
                            "search": ast.Constant(value=f"%{search}%"),
                        },
                    ),
                ),
            ]
        )
        return HogQLPropertyFilter(key=condition.to_hogql())
