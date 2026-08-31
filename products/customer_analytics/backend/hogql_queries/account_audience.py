"""Account selection for workflows batch audiences: HogQL over ``system.accounts``.

The custom-property predicates mirror the frontend compiler in
``products/customer_analytics/frontend/components/Accounts/accountsCustomPropertyFilters.ts``;
keep the two in sync so a trigger audience matches what the Accounts scene previews.
"""

from typing import Any, cast
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.synthetic_user import SyntheticUser

from products.customer_analytics.backend.models import CustomPropertyDefinition, DataType
from products.workflows.backend.services.account_audience import (
    AccountAudienceCustomPropertyFilter,
    AccountAudienceFilters,
)


class _AudiencePrincipal(SyntheticUser):
    """Service principal for audience resolution: batch dispatch runs without a request user,
    and ``system.accounts`` is hidden from principals whose scopes don't cover ``account``."""

    def readable_system_table_access_scopes(self) -> set[str]:
        return {"account"}


def _audience_principal(team: Team) -> User:
    return cast(User, _AudiencePrincipal(team, distinct_id=f"workflows-account-audience-{team.pk}"))


_RANGE_OPERATORS = {
    "gt": ast.CompareOperationOp.Gt,
    "gte": ast.CompareOperationOp.GtEq,
    "lt": ast.CompareOperationOp.Lt,
    "lte": ast.CompareOperationOp.LtEq,
}

_DATE_OPERATORS = {
    "is_date_exact": ast.CompareOperationOp.Eq,
    "is_date_before": ast.CompareOperationOp.Lt,
    "is_date_after": ast.CompareOperationOp.Gt,
}

_BOOLEAN_LITERALS: dict[str, list[str]] = {
    "true": ["true", "1"],
    "1": ["true", "1"],
    "false": ["false", "0"],
    "0": ["false", "0"],
}


def list_account_external_ids_for_audience(
    team: Team, filters: AccountAudienceFilters, *, cursor: str | None, limit: int
) -> list[str]:
    where = _where_exprs(team, filters)
    if cursor is not None:
        where.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["accounts", "external_id"]),
                right=ast.Constant(value=cursor),
            )
        )
    query = ast.SelectQuery(
        select=[ast.Field(chain=["accounts", "external_id"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["system", "accounts"]), alias="accounts"),
        where=ast.And(exprs=where),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["accounts", "external_id"]), order="ASC")],
        limit=ast.Constant(value=limit),
    )
    tag_queries(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY)
    response = execute_hogql_query(query=query, team=team, user=_audience_principal(team))
    return [str(row[0]) for row in response.results or []]


def count_accounts_for_audience(team: Team, filters: AccountAudienceFilters) -> int:
    query = ast.SelectQuery(
        select=[ast.Call(name="count", args=[])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["system", "accounts"]), alias="accounts"),
        where=ast.And(exprs=_where_exprs(team, filters)),
    )
    tag_queries(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY)
    response = execute_hogql_query(query=query, team=team, user=_audience_principal(team))
    return int(response.results[0][0]) if response.results else 0


def _where_exprs(team: Team, filters: AccountAudienceFilters) -> list[ast.Expr]:
    where: list[ast.Expr] = [
        parse_expr("isNotNull(accounts.external_id) AND accounts.external_id != ''"),
        parse_expr("isNull(accounts.ignored_at)"),
    ]

    if filters.tag_names:
        subquery = parse_select(
            """
            SELECT ti.account_id
            FROM system._account_tagged_items AS ti
            INNER JOIN system.tags AS t ON t.id = ti.tag_id
            WHERE t.name IN {tag_names}
            """,
            {"tag_names": ast.Constant(value=list(filters.tag_names))},
        )
        where.append(parse_expr("accounts.id IN {subquery}", {"subquery": subquery}))

    if filters.all_roles_unassigned:
        where.append(
            parse_expr(
                "accounts.id NOT IN {subquery}",
                {
                    "subquery": parse_select(
                        "SELECT account_id FROM system.account_relationships"
                        " WHERE isNull(ended_at) AND isNotNull(user_id)"
                    )
                },
            )
        )

    if filters.assigned_to_user_ids:
        where.append(
            parse_expr(
                "accounts.id IN {subquery}",
                {
                    "subquery": parse_select(
                        "SELECT account_id FROM system.account_relationships"
                        " WHERE isNull(ended_at) AND user_id IN {user_ids}",
                        {"user_ids": ast.Constant(value=list(filters.assigned_to_user_ids))},
                    )
                },
            )
        )

    if filters.custom_properties:
        definitions = {
            definition.id: definition
            for definition in CustomPropertyDefinition.objects.for_team(team.pk).filter(
                id__in=[f.definition_id for f in filters.custom_properties]
            )
        }
        for custom_property_filter in filters.custom_properties:
            definition = definitions.get(custom_property_filter.definition_id)
            # A dropped predicate would silently broaden the audience to every account,
            # so an unresolvable filter fails the resolution instead.
            if definition is None:
                raise ValueError(
                    f"Audience filter references a deleted or unknown custom property "
                    f"({custom_property_filter.definition_id}). Remove it from the trigger."
                )
            predicate = _custom_property_filter_expr(custom_property_filter, definition)
            if predicate is None:
                raise ValueError(
                    f"Audience filter on '{definition.name}' has a value incompatible with its "
                    f"{definition.display_type} type."
                )
            where.append(predicate)

    return where


def _custom_property_filter_expr(
    filter: AccountAudienceCustomPropertyFilter, definition: CustomPropertyDefinition
) -> ast.Expr | None:
    column = _value_column(filter.definition_id)
    operator = filter.operator

    if operator == "is_set":
        return ast.Call(name="isNotNull", args=[column])
    if operator == "is_not_set":
        return ast.Call(name="isNull", args=[column])

    values = _normalize_values(filter.value)
    if not values:
        return None
    data_type = definition.data_type

    if operator in ("exact", "is_not"):
        negated = operator == "is_not"
        if data_type == DataType.NUMERIC:
            numbers = _finite_numbers(values)
            if not numbers:
                return None
            comparison = _equality(ast.Call(name="toFloatOrNull", args=[column]), numbers, negated)
        elif data_type == DataType.BOOLEAN:
            literals = sorted(
                {literal for value in values for literal in _BOOLEAN_LITERALS.get(str(value).lower(), [])}
            )
            if not literals:
                return None
            comparison = _equality(column, literals, negated)
        else:
            comparison = _equality(column, [str(value) for value in values], negated)
        return _include_unset(comparison) if negated else comparison

    if operator in ("icontains", "not_icontains"):
        any_match = ast.Or(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike, left=column, right=ast.Constant(value=f"%{value}%")
                )
                for value in values
            ]
        )
        return _include_unset(ast.Not(expr=any_match)) if operator == "not_icontains" else any_match

    if operator in ("regex", "not_regex"):
        any_match = ast.Or(
            exprs=[ast.Call(name="match", args=[column, ast.Constant(value=str(value))]) for value in values]
        )
        return _include_unset(ast.Not(expr=any_match)) if operator == "not_regex" else any_match

    if operator in _RANGE_OPERATORS:
        numbers = _finite_numbers(values[:1])
        if not numbers:
            return None
        return ast.CompareOperation(
            op=_RANGE_OPERATORS[operator],
            left=ast.Call(name="toFloatOrNull", args=[column]),
            right=ast.Constant(value=numbers[0]),
        )

    if operator in _DATE_OPERATORS:
        return ast.CompareOperation(
            op=_DATE_OPERATORS[operator],
            left=ast.Call(name="parseDateTimeBestEffort", args=[column]),
            right=ast.Call(name="parseDateTimeBestEffort", args=[ast.Constant(value=str(values[0]))]),
        )

    return None


def _value_column(definition_id: UUID) -> ast.Field:
    return ast.Field(chain=["accounts", "custom_properties", "values", str(definition_id)])


def _normalize_values(value: Any) -> list[Any]:
    raw = value if isinstance(value, list) else [] if value is None else [value]
    return [entry for entry in raw if entry is not None and entry != ""]


def _finite_numbers(values: list[Any]) -> list[float]:
    numbers: list[float] = []
    for value in values:
        try:
            numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    return numbers


def _equality(target: ast.Expr, values: list[Any], negated: bool) -> ast.Expr:
    if len(values) == 1:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq if negated else ast.CompareOperationOp.Eq,
            left=target,
            right=ast.Constant(value=values[0]),
        )
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn if negated else ast.CompareOperationOp.In,
        left=target,
        right=ast.Constant(value=values),
    )


def _include_unset(predicate: ast.Expr) -> ast.Expr:
    # The lazy join yields NULL for accounts without a value; a bare negation would
    # drop them, but "is not X" must keep them. Mirrors the frontend's ifNull(..., true).
    return ast.Call(name="ifNull", args=[predicate, ast.Constant(value=True)])
