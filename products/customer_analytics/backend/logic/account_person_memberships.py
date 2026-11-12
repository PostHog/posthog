from typing import cast

from posthog.schema import CachedHogQLQueryResponse, HogQLQuery, HogQLQueryResponse

from posthog.hogql import ast

from posthog.clickhouse.query_tagging import Feature, Product, get_query_tag_value, tags_context
from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.person.util import get_persons_by_uuids

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.facade.contracts import PersonAccount, PersonAccounts
from products.customer_analytics.backend.logic.account_persons import AccountPersonsReader, MembershipTableReferences
from products.customer_analytics.backend.models.account import Account


class AccountPersonMembershipsQueryRunner(HogQLQueryRunner):
    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        query = super().to_query()
        MembershipTableReferences().visit(query)
        assert (
            isinstance(query, ast.SelectQuery)
            and query.select_from is not None
            and query.select_from.next_join is not None
        )
        # HogQL reparsing drops the alias before GLOBAL JOIN, so add the modifier after parsing.
        query.select_from.next_join.join_type = "GLOBAL INNER JOIN"
        return query


def list_person_accounts(
    reader: AccountPersonsReader, person_ids: list[str], access: UserAccessControl
) -> list[PersonAccounts]:
    if reader.group_key is None:
        return []
    persons = get_persons_by_uuids(reader.team.pk, person_ids)
    distinct_ids = {distinct_id for person in persons for distinct_id in person.distinct_ids}
    if not distinct_ids:
        return []
    query = reader.parse_membership_query(
        """
        SELECT pdi.person_id, groupUniqArray(membership.group_key)
        FROM posthog.person_group_membership AS membership
        INNER JOIN (
            SELECT distinct_id, argMax(person_id, version) AS person_id
            FROM raw_person_distinct_ids
            WHERE distinct_id IN {distinct_ids}
            GROUP BY distinct_id
            HAVING argMax(is_deleted, version) = 0 AND person_id IN {person_ids}
        ) AS pdi ON membership.distinct_id = pdi.distinct_id
        WHERE membership.group_type_index = {group_type_index}
            AND membership.distinct_id IN {distinct_ids}
        GROUP BY pdi.person_id
        HAVING has(groupUniqArray(membership.group_key), {account_key})
        LIMIT 500
        """,
        placeholders={
            "distinct_ids": ast.Tuple(exprs=[ast.Constant(value=distinct_id) for distinct_id in sorted(distinct_ids)]),
            "person_ids": ast.Tuple(exprs=[ast.Constant(value=person_id) for person_id in person_ids]),
            "group_type_index": ast.Constant(value=reader.group_type_index),
            "account_key": ast.Constant(value=reader.group_key),
        },
    )
    with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.ACCOUNTS):
        runner = AccountPersonMembershipsQueryRunner(
            query=HogQLQuery(query=query.to_hogql()), team=reader.team, workload=Workload.ONLINE, user=reader.user
        )
        runner.is_query_service = get_query_tag_value("access_method") == "personal_api_key"
        response = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=reader.user)
    assert isinstance(response, (HogQLQueryResponse, CachedHogQLQueryResponse))
    rows = cast(list[tuple[str, list[str]]], response.results or [])
    keys = {key for _, group_keys in rows for key in group_keys}
    accounts = access.filter_queryset_by_access_level(
        Account.objects.for_team(reader.team.pk).filter(external_id__in=keys)
    ).values_list("external_id", "id", "name")
    account_by_key: dict[str, PersonAccount] = {
        key: {"id": str(account_id), "name": name} for key, account_id, name in accounts if key is not None
    }
    return [
        {
            "person_id": str(person_id),
            "accounts": sorted(
                [account_by_key[key] for key in group_keys if key in account_by_key],
                key=lambda account: (account["name"].casefold(), account["id"]),
            ),
        }
        for person_id, group_keys in rows
    ]
