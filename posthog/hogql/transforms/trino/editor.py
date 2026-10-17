from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.direct_sql import get_adapter_for_source
from posthog.hogql.transforms.trino.contracts import TrinoExpansionMode

from posthog.dataclasses import frozen
from posthog.schema_enums import PersonsOnEventsMode

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.models import Team, User

    from products.warehouse_sources.backend.facade.models import ExternalDataSource


@frozen
class TrinoEditorTarget:
    context: HogQLContext
    expansion_mode: TrinoExpansionMode


def uses_trino_compiler(team: Team, source: ExternalDataSource) -> bool:
    adapter = get_adapter_for_source(source, team=team)
    return adapter is not None and adapter.engine == "trino"


def prepare_trino_editor_target(
    *,
    team: Team,
    user: User | None,
    source: ExternalDataSource | None,
    hosted: bool = False,
    context: HogQLContext,
    modifiers: HogQLQueryModifiers | None,
) -> TrinoEditorTarget:
    from products.managed_warehouse.backend.facade.client import (  # noqa: PLC0415 -- managed target resolution stays behind the product facade
        is_managed_trino_editor_connection,
        prepare_managed_trino_editor_context,
    )

    if source is not None and source.team_id != team.pk:
        raise ValueError("The selected connection does not belong to this project")
    if hosted or (
        source is not None
        and uses_trino_compiler(team, source)
        and source.is_dynamic_managed_warehouse
        and is_managed_trino_editor_connection(team.pk, str(source.id))
    ):
        managed_context = prepare_managed_trino_editor_context(
            team.pk,
            user=user,
            user_access_control=context.user_access_control,
            bypass_warehouse_access_control=context.bypass_warehouse_access_control,
            modifiers=modifiers,
        )
        managed_context.limit_context = context.limit_context
        managed_context.limit_top_select = context.limit_top_select
        managed_context.timings = context.timings
        return TrinoEditorTarget(context=managed_context, expansion_mode=TrinoExpansionMode.DJANGO)
    if source is None or not uses_trino_compiler(team, source):
        raise ValueError("The selected connection does not use Trino")
    database = Database.create_for(
        team=team,
        user=user,
        user_access_control=context.user_access_control,
        modifiers=context.modifiers,
        timings=context.timings,
        connection_id=str(source.id),
        bypass_warehouse_access_control=context.bypass_warehouse_access_control,
        use_cached_sources=context.use_cached_sources,
        trigger="trino",
    )
    return TrinoEditorTarget(
        context=replace(
            context,
            database=database,
            team_id=None,
            team=None,
            user=None,
            is_direct_query=True,
            enable_select_queries=True,
            restricted_properties=set(),
            modifiers=context.modifiers.model_copy(
                update={"personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS}
            ),
        ),
        expansion_mode=TrinoExpansionMode.PURE,
    )
