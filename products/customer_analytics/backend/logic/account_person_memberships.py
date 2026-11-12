from typing import TypedDict, cast

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.logic.account_persons import AccountPersonsReader
from products.customer_analytics.backend.models.account import Account


class PersonAccount(TypedDict):
    id: str
    name: str


class PersonAccounts(TypedDict):
    person_id: str
    accounts: list[PersonAccount]


def list_person_accounts(
    reader: AccountPersonsReader, person_ids: list[str], access: UserAccessControl
) -> list[PersonAccounts]:
    query = reader.parse_membership_query(
        """
        SELECT pdi.person_id, groupUniqArray(membership.group_key)
        FROM posthog.person_group_membership AS membership
        INNER JOIN (
            SELECT distinct_id, argMax(person_id, version) AS person_id
            FROM raw_person_distinct_ids
            WHERE distinct_id IN (
                SELECT distinct_id FROM raw_person_distinct_ids WHERE person_id IN {person_ids}
            )
            GROUP BY distinct_id
            HAVING argMax(is_deleted, version) = 0 AND person_id IN {person_ids}
        ) AS pdi ON membership.distinct_id = pdi.distinct_id
        WHERE membership.group_type_index = {group_type_index}
            AND pdi.person_id IN (SELECT person_id FROM {source})
        GROUP BY pdi.person_id
        LIMIT 500
        """,
        placeholders={
            "person_ids": ast.Tuple(exprs=[ast.Constant(value=person_id) for person_id in person_ids]),
            "group_type_index": ast.Constant(value=reader.group_type_index),
            "source": reader.get_source_query(),
        },
    )
    assert query.select_from is not None and query.select_from.next_join is not None
    query.select_from.next_join.join_type = "GLOBAL INNER JOIN"
    with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.ACCOUNTS):
        response = execute_hogql_query(query, team=reader.team, user=reader.user, workload=Workload.ONLINE)
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
