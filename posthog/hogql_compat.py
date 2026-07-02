"""LEGACY: Django ``Team`` boundary shims for HogQL.

Every function here is a thin wrapper that takes a Django ``Team`` (or ``Action``), builds
a ``DataProvider`` via ``provider_for``, and delegates to the engine's Django-free
``*_core(DataProvider)`` function. They exist only so the many call sites that already hold
a ``Team`` (query runners, product backends) keep working without each building a provider.

This module lives OUTSIDE the engine package (``posthog/hogql/``) on purpose: the engine must
not import the ORM-backed provider or read the ORM mid-compile, and these shims do both
(``provider_for`` / ``Database.create_for``). Keeping them here is what lets
``posthog/hogql/{property,filters,variables}.py`` avoid importing the Django provider.
The load-bearing logic is the ``*_core`` functions in those modules — this is the legacy
surface in front of them.

To retire a shim: migrate its callers to build a ``DataProvider`` (or pass a
``HogQLTeamContext``) and call the matching ``*_core`` function directly, then delete the
shim here. Nothing in the engine needs to change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional, TypeVar

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.filters import replace_filters_core
from posthog.hogql.property import (
    _LowercaseIndexRewriter,
    apply_path_cleaning_core,
    entity_to_expr_core,
    property_to_expr_core,
    steps_to_expr_core,
)
from posthog.hogql.variables import replace_variables_core

from posthog.hogql_django_provider import provider_for

if TYPE_CHECKING:
    from posthog.schema import (
        CohortPropertyFilter,
        DataWarehousePersonPropertyFilter,
        DataWarehousePropertyFilter,
        ElementPropertyFilter,
        EmptyPropertyFilter,
        ErrorTrackingIssueFilter,
        EventMetadataPropertyFilter,
        EventPropertyFilter,
        FeaturePropertyFilter,
        FlagPropertyFilter,
        GroupPropertyFilter,
        HogQLFilters,
        HogQLPropertyFilter,
        HogQLVariable,
        LogEntryPropertyFilter,
        LogPropertyFilter,
        PersonMetadataPropertyFilter,
        PersonPropertyFilter,
        PropertyGroupFilter,
        PropertyGroupFilterValue,
        RecordingPropertyFilter,
        RetentionEntity,
        RevenueAnalyticsPropertyFilter,
        SessionPropertyFilter,
        SpanPropertyFilter,
        WorkflowVariablePropertyFilter,
    )

    from posthog.models import Property, Team
    from posthog.models.property import PropertyGroup

    from products.actions.backend.models.action import Action, ActionStepJSON

T = TypeVar("T", bound=ast.Expr)


def property_to_expr(
    property: (
        list
        | dict
        | PropertyGroup
        | PropertyGroupFilter
        | PropertyGroupFilterValue
        | Property
        | ast.Expr
        | EventPropertyFilter
        | PersonPropertyFilter
        | ElementPropertyFilter
        | SessionPropertyFilter
        | EventMetadataPropertyFilter
        | PersonMetadataPropertyFilter
        | RevenueAnalyticsPropertyFilter
        | CohortPropertyFilter
        | RecordingPropertyFilter
        | LogEntryPropertyFilter
        | GroupPropertyFilter
        | FeaturePropertyFilter
        | FlagPropertyFilter
        | HogQLPropertyFilter
        | EmptyPropertyFilter
        | DataWarehousePropertyFilter
        | DataWarehousePersonPropertyFilter
        | ErrorTrackingIssueFilter
        | LogPropertyFilter
        | SpanPropertyFilter
        | WorkflowVariablePropertyFilter
    ),
    team: Team,
    scope: Literal[
        "event", "person", "group", "session", "replay", "replay_entity", "revenue_analytics", "log_resource"
    ] = "event",
    strict: bool = False,
) -> ast.Expr:
    return property_to_expr_core(property, provider_for(team), scope, strict=strict)


def apply_path_cleaning(path_expr: ast.Expr, team: Team) -> ast.Expr:
    return apply_path_cleaning_core(path_expr, provider_for(team))


def steps_to_expr(steps: list[ActionStepJSON], team: Team, events_alias: Optional[str] = None) -> ast.Expr:
    return steps_to_expr_core(steps, provider_for(team), events_alias)


def action_to_expr(action: Action, events_alias: Optional[str] = None) -> ast.Expr:
    return steps_to_expr(action.steps, action.team, events_alias)


def entity_to_expr(entity: RetentionEntity, team: Team) -> ast.Expr:
    return entity_to_expr_core(entity, provider_for(team))


def get_lowercase_index_hint(property, team: Team) -> ast.Call:
    """
    Returns an index hint for a case insensitive index on `lower(key)`
    e.g. for the property `body ILIKE '%STR%'` return `indexHint(lower(body) ILIKE '%str%')`
         this means we can use ngram indexes on `lower(body)` efficiently
    """
    expr = property_to_expr(property, team=team)
    return ast.Call(name="indexHint", args=[_LowercaseIndexRewriter().visit(expr)])


def replace_filters(node: T, filters: Optional[HogQLFilters], team: Team, database: Optional[Database] = None) -> T:
    if database is None:
        database = Database.create_for(team=team)
    return replace_filters_core(node, filters, provider_for(team), database)


def replace_variables(node: T, variables: list[HogQLVariable], team: Team) -> T:
    return replace_variables_core(node, variables, provider_for(team))
