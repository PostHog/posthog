import json
from datetime import datetime
from typing import cast

from rest_framework.exceptions import ValidationError

from posthog.schema import ActorsQuery, HogQLQuery, HogQLQueryModifiers, PersonPropertyFilter, PersonsArgMaxVersion

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import HogQLPrinter

from posthog.api.person import PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.hogql_queries.actor_strategies import PersonStrategy
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.paginators import HogQLHasMorePaginator
from posthog.models import Team, User

from products.access_control.backend.property_access_control import get_restricted_property_names
from products.event_definitions.backend.models.property_definition import PropertyDefinition


@frozen
class AccountPerson:
    id: str
    name: str
    distinct_ids: list[str]
    properties: dict[str, object]
    account_first_seen: datetime
    account_last_seen: datetime


@frozen
class AccountPersonsPage:
    results: list[AccountPerson]
    limit: int
    offset: int
    has_more: bool


def membership_source_query(group_type_index: int, group_key: str) -> ast.SelectQuery:
    # Narrow mappings before version resolution so an account lookup does not aggregate the whole project.
    return cast(
        ast.SelectQuery,
        parse_select(
            """
        SELECT pdi.person_id AS person_id,
               min(membership.first_seen) AS account_first_seen,
               max(membership.last_seen) AS account_last_seen,
               groupUniqArray(membership.distinct_id) AS distinct_ids
        FROM posthog.person_group_membership AS membership
        INNER JOIN person_distinct_ids AS pdi ON membership.distinct_id = pdi.distinct_id
        WHERE membership.group_type_index = {index} AND membership.group_key = {key}
          AND pdi.distinct_id IN (
              SELECT distinct_id FROM posthog.person_group_membership
              WHERE group_type_index = {index} AND group_key = {key}
          )
        GROUP BY pdi.person_id
        """,
            placeholders={"index": ast.Constant(value=group_type_index), "key": ast.Constant(value=group_key)},
        ),
    )


class AccountPersonStrategy(PersonStrategy):
    def __init__(
        self, *, team: Team, query: ActorsQuery, paginator: HogQLHasMorePaginator, user: User, restricted: set[str]
    ) -> None:
        super().__init__(team=team, query=query, paginator=paginator, user=user)
        self.restricted = restricted

    def filter_conditions(self) -> list[ast.Expr]:
        search = self.query.search.strip() if self.query.search else ""
        query_without_search = self.query.model_copy(update={"search": None})
        conditions = PersonStrategy(
            team=self.team, query=query_without_search, paginator=self.paginator
        ).filter_conditions()
        if search:
            value = ast.Constant(value=f"%{search}%")
            fields = [ast.Field(chain=["persons", "id"])] + [
                ast.Field(chain=["persons", "properties", key])
                for key in ("name", "email", "Email")
                if key not in self.restricted
            ]
            conditions.append(
                ast.Or(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike, left=ast.Call(name="toString", args=[field]), right=value
                        )
                        for field in fields
                    ]
                    + [
                        parse_expr(
                            "arrayExists(distinct_id -> ilike(distinct_id, {search}), source.distinct_ids)",
                            placeholders={"search": value},
                        )
                    ]
                )
            )
        return conditions


def list_account_persons(
    *,
    team: Team,
    user: User,
    group_type_index: int | None,
    group_key: str | None,
    limit: int,
    offset: int,
    search: str = "",
    select: list[str],
    properties: list[PersonPropertyFilter] | None = None,
    order_by: str = "-account_last_seen",
) -> AccountPersonsPage:
    restricted = get_restricted_property_names(team_id=team.id, user=user, property_type=PropertyDefinition.Type.PERSON)
    selected = [key for key in select if key not in restricted]
    sort_key = order_by.removeprefix("-")
    if sort_key in restricted or any(prop.key in restricted for prop in properties or []):
        raise ValidationError("Remove restricted person properties from filters and sorting.")
    if group_type_index is None or group_type_index not in range(5) or group_key is None:
        return AccountPersonsPage(results=[], limit=limit, offset=offset, has_more=False)

    printer = HogQLPrinter(context=HogQLContext(team_id=team.id))
    display_keys = team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    display_name = ast.Call(
        name="coalesce",
        args=[
            ast.Call(
                name="nullIf",
                args=[
                    ast.Call(name="toString", args=[ast.Field(chain=["persons", "properties", key])]),
                    ast.Constant(value=""),
                ],
            )
            for key in display_keys
            if key not in restricted
        ]
        + [ast.Call(name="toString", args=[ast.Field(chain=["persons", "id"])])],
    )
    columns: list[ast.Expr] = [
        ast.Field(chain=["persons", "id"]),
        ast.Alias(alias="name", expr=display_name),
        ast.Field(chain=["source", "distinct_ids"]),
        ast.Field(chain=["source", "account_first_seen"]),
        ast.Field(chain=["source", "account_last_seen"]),
    ] + [
        ast.Call(name="JSONExtractRaw", args=[ast.Field(chain=["persons", "properties"]), ast.Constant(value=key)])
        for key in selected
    ]
    sort_field = (
        ast.Field(chain=["source", sort_key])
        if sort_key in ("account_first_seen", "account_last_seen")
        else ast.Field(chain=["persons", "properties", sort_key])
    )
    order = ast.OrderExpr(expr=sort_field, order="DESC" if order_by.startswith("-") else "ASC")
    query = ActorsQuery(
        source=HogQLQuery(
            query=printer.visit(membership_source_query(group_type_index, group_key)),
            modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V2),
        ),
        select=[printer.visit(column) for column in columns],
        orderBy=[printer.visit(order), "persons.id ASC"],
        limit=limit,
        offset=offset,
        search=search,
        properties=properties,
    )
    tag_queries(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY, name="account-persons")
    runner = ActorsQueryRunner(team=team, query=query, user=user)
    runner.user = user
    runner.strategy = AccountPersonStrategy(
        team=team, query=query, paginator=runner.paginator, user=user, restricted=restricted
    )
    response = runner.calculate()
    results = [
        AccountPerson(
            id=str(row[0]),
            name=row[1],
            distinct_ids=sorted(row[2]),
            account_first_seen=row[3],
            account_last_seen=row[4],
            properties={key: json.loads(value) if value else None for key, value in zip(selected, row[5:])},
        )
        for row in response.results
    ]
    return AccountPersonsPage(results=results, limit=limit, offset=offset, has_more=bool(response.hasMore))
