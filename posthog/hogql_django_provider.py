import datetime
from typing import TYPE_CHECKING, Any, Optional, cast

from django.db import models
from django.db.models import Prefetch, Q
from django.db.models.functions.comparison import Coalesce
from django.utils import timezone

import posthoganalytics

from posthog.hogql.data_provider import (
    ActionRef,
    ActionScope,
    CohortRef,
    CohortRefKind,
    DataProvider,
    InsightVariableInfo,
    MaterializedColumnInfo,
    PropertyKind,
    PropertyTypeInfo,
    PropertyTypes,
    RestrictedProperty,
)
from posthog.hogql.team_context import HogQLTeamContext

from posthog.clickhouse.materialized_columns import (
    DMAT_STRING_COLUMN_NAME_PREFIX,
    TablesWithMaterializedColumns,
    get_materialized_column_for_property,
)
from posthog.models import PropertyDefinition, Team
from posthog.models.materialized_column_slots import MaterializedColumnSlot, MaterializedColumnSlotState
from posthog.models.property import PropertyName, TableColumn

from products.access_control.backend.property_access_control import get_restricted_properties_for_team
from products.actions.backend.models.action import Action
from products.cohorts.backend.models.calculation_history import CohortCalculationHistory
from products.cohorts.backend.models.cohort import Cohort
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.product_analytics.backend.models.insight_variable import InsightVariable
from products.warehouse_sources.backend.models.util import get_view_or_table_by_name

if TYPE_CHECKING:
    from posthog.hogql import ast

    from posthog.models import User

INLINE_COHORT_THRESHOLD_SECONDS = 10


def _is_inline_flag_enabled(team: Team) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            "inline-cohort-calculation",
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def _is_cohort_fast_enough_to_inline(cohort_id: int) -> bool:
    seven_days_ago = timezone.now() - datetime.timedelta(days=7)
    recent_calcs = list(
        CohortCalculationHistory.objects.filter(
            cohort_id=cohort_id,
            finished_at__isnull=False,
            started_at__gte=seven_days_ago,
        )
        .order_by("-started_at")
        .values_list("error", "started_at", "finished_at")
    )
    if not recent_calcs:
        return True

    if recent_calcs[0][0] is not None:
        return False

    durations = sorted(
        (finished_at - started_at).total_seconds() for error, started_at, finished_at in recent_calcs if error is None
    )
    return not durations or durations[len(durations) // 2] < INLINE_COHORT_THRESHOLD_SECONDS


def _property_definitions_for_project(project_id: int):
    return PropertyDefinition.objects.alias(
        effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
    ).filter(effective_project_id=project_id)


class DjangoDataProvider:
    """The ORM-backed ``DataProvider`` — the Django side of the engine's data port.

    Holds the requesting team (fetched lazily when only an id is known) and answers the
    engine's mid-compile data questions by querying the database. Reads happen at the
    moment the engine asks, exactly as they did when engine code queried the ORM
    directly — only the routing changed.
    """

    def __init__(self, team: Optional[Team] = None, team_id: Optional[int] = None, user: Optional["User"] = None):
        self._team = team
        self._team_id = team_id if team_id is not None else (team.id if team is not None else None)
        self._user = user
        self._team_context: Optional[HogQLTeamContext] = None
        # Action rows fetched by actions() are kept so a following action_expr() call
        # converts the already-loaded row instead of re-querying.
        self._action_rows: dict[int, Action] = {}

    @property
    def team(self) -> Team:
        if self._team is None:
            if self._team_id is None:
                raise ValueError("DjangoDataProvider needs a team or team_id to answer data queries")
            self._team = Team.objects.get(id=self._team_id)
        return self._team

    @property
    def team_context(self) -> HogQLTeamContext:
        if self._team_context is None:
            self._team_context = HogQLTeamContext.from_team(self.team)
        return self._team_context

    def person_warehouse_property_type(self, field_name: str | int, property_key: str) -> Optional[str]:
        # TODO: pass id of table item being filtered on instead of searching through joins
        current_join: DataWarehouseJoin | None = (
            DataWarehouseJoin.objects.filter(Q(deleted__isnull=True) | Q(deleted=False))
            .filter(team=self.team, source_table_name="persons", field_name=field_name)
            .first()
        )

        if not current_join:
            raise Exception(f"Could not find join for key {field_name}")

        table_or_view = get_view_or_table_by_name(self.team, current_join.joining_table_name)
        if not table_or_view:
            raise Exception(f"Could not find table or view for key {field_name}")

        if table_or_view.columns is not None:
            prop_type_dict = table_or_view.columns.get(property_key, None)
            if prop_type_dict is not None:
                return prop_type_dict.get("hogql")

        return None

    def persons_join_uses_inner_join(self) -> bool:
        organization = self.team.organization
        # TODO: @raquelmsmith: Remove flag check and use left join for all once deletes are caught up
        return bool(
            posthoganalytics.feature_enabled(
                "personless-events-not-supported",
                str(self.team.uuid),
                groups={"organization": str(organization.id)},
                group_properties={
                    "organization": {
                        "id": str(organization.id),
                        "created_at": organization.created_at,
                    }
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )

    def property_type(self, kind: PropertyKind, name: str, group_type_index: Optional[int] = None) -> Optional[str]:
        if kind == "person":
            property_types = _property_definitions_for_project(self.team.project_id).filter(
                name=name,
                type=PropertyDefinition.Type.PERSON,
            )
        elif kind == "group":
            property_types = _property_definitions_for_project(self.team.project_id).filter(
                name=name,
                type=PropertyDefinition.Type.GROUP,
                group_type_index=group_type_index,
            )
        else:
            property_types = _property_definitions_for_project(self.team.project_id).filter(
                name=name,
                type=PropertyDefinition.Type.EVENT,
            )
        return property_types[0].property_type if len(property_types) > 0 else None

    def property_types(
        self,
        event_properties: list[str],
        person_properties: list[str],
        group_properties: dict[int, list[str]],
    ) -> PropertyTypes:
        # Load event property definitions with their materialized slots in a single query
        event_property_definitions = (
            _property_definitions_for_project(self.team.project_id)
            .filter(
                name__in=event_properties,
                type__in=[None, PropertyDefinition.Type.EVENT],
            )
            .prefetch_related(
                Prefetch(
                    "materialized_column_slots",
                    queryset=MaterializedColumnSlot.objects.filter(
                        team_id=self.team.id, state=MaterializedColumnSlotState.READY
                    ),
                )
            )
            if event_properties
            else []
        )

        event: dict[str, PropertyTypeInfo] = {}
        for prop_def in event_property_definitions:
            property_type = prop_def.property_type
            if not property_type:
                continue

            prop_info: PropertyTypeInfo = {"type": property_type}
            slot = prop_def.materialized_column_slots.first()
            if slot:
                prop_info["dmat"] = f"{DMAT_STRING_COLUMN_NAME_PREFIX}{slot.slot_index}"

            event[prop_def.name] = prop_info

        person_property_values = (
            _property_definitions_for_project(self.team.project_id)
            .filter(
                name__in=person_properties,
                type=PropertyDefinition.Type.PERSON,
            )
            .values_list("name", "property_type")
            if person_properties
            else []
        )
        person: dict[str, PropertyTypeInfo] = {
            name: {"type": property_type} for name, property_type in person_property_values if property_type
        }

        group: dict[str, PropertyTypeInfo] = {}
        for group_id, names in group_properties.items():
            if not names:
                continue
            group_property_values = (
                _property_definitions_for_project(self.team.project_id)
                .filter(
                    name__in=names,
                    type=PropertyDefinition.Type.GROUP,
                    group_type_index=group_id,
                )
                .values_list("name", "property_type")
            )
            group.update(
                {
                    f"{group_id}_{name}": {"type": property_type}
                    for name, property_type in group_property_values
                    if property_type
                }
            )

        return PropertyTypes(event=event, person=person, group=group)

    def materialized_column(self, table: str, column: str, property_name: str) -> Optional[MaterializedColumnInfo]:
        # Gated on the MATERIALIZED_COLUMNS_ENABLED instance setting inside the lookup;
        # when disabled every property is reported as unmaterialized.
        mat_column = get_materialized_column_for_property(
            cast(TablesWithMaterializedColumns, table),
            cast(TableColumn, column),
            cast(PropertyName, property_name),
        )
        if mat_column is None:
            return None
        return MaterializedColumnInfo(
            name=mat_column.name,
            type=mat_column.type,
            is_nullable=mat_column.is_nullable,
            has_minmax_index=mat_column.has_minmax_index,
            has_bloom_filter_index=mat_column.has_bloom_filter_index,
            has_ngram_lower_index=mat_column.has_ngram_lower_index,
            has_bloom_filter_lower_index=mat_column.has_bloom_filter_lower_index,
        )

    def actions(self, ref: int | str, scope: ActionScope) -> list[ActionRef]:
        if scope == "team":
            rows = Action.objects.filter(pk=ref, team_id=self.team.id).all()
        elif isinstance(ref, str):
            rows = Action.objects.filter(name=ref, team__project_id=self.team.project_id).all()
        else:
            rows = Action.objects.filter(id=ref, team__project_id=self.team.project_id).all()

        refs = []
        for row in rows:
            self._action_rows[row.pk] = row
            refs.append(ActionRef(id=row.pk, name=row.name))
        return refs

    def action_expr(self, action_id: int, events_alias: Optional[str] = None) -> Optional["ast.Expr"]:
        # Deferred import: property.py itself imports this module for its boundary shims.
        from posthog.hogql.property import steps_to_expr_core  # noqa: PLC0415

        row = self._action_rows.get(action_id)
        if row is None:
            row = Action.objects.filter(pk=action_id, team__project_id=self.team.project_id).first()
            if row is None:
                return None
            self._action_rows[action_id] = row
        # Resolve the action's steps through this provider — not action_to_expr, which would rebuild a
        # second DjangoDataProvider from row.team. We are already the provider, scoped to row's project.
        return steps_to_expr_core(row.steps, self, events_alias=events_alias)

    def insight_variables(self, variable_ids: list[str]) -> list[InsightVariableInfo]:
        rows = InsightVariable.objects.filter(team_id=self.team.id, id__in=variable_ids).all()
        return [InsightVariableInfo(code_name=row.code_name, default_value=row.default_value) for row in rows]

    def expand_query(self, query_node: Any) -> "ast.SelectQuery | ast.SelectSetQuery":
        # Deferred: pulls in the whole query-runner universe; keep it off the import path.
        from posthog.hogql_queries.query_runner import get_query_runner  # noqa: PLC0415

        return get_query_runner(query_node, self.team).to_query()

    def cohort_id(self, ref: int | str) -> int:
        return Cohort.objects.get(team__project_id=self.team.project_id, id=ref).pk

    def cohorts(self, ref: int | str, by: CohortRefKind) -> list[CohortRef]:
        queryset = Cohort.objects.filter(team__project_id=self.team.project_id, deleted=False)
        queryset = queryset.filter(name=ref) if by == "name" else queryset.filter(id=ref)
        return [
            CohortRef(id=id, is_static=is_static, version=version, name=name)
            for id, is_static, version, name in queryset.values_list("id", "is_static", "version", "name")
        ]

    def inline_cohort(self, cohort_id: int, auto_gated: bool) -> Optional["ast.SelectQuery | ast.SelectSetQuery"]:
        # Deferred: pulls in the query-runner universe; keep it off the import path.
        from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery  # noqa: PLC0415

        if auto_gated:
            if not _is_inline_flag_enabled(self.team):
                return None
            if not _is_cohort_fast_enough_to_inline(cohort_id):
                return None

        cohort = Cohort.objects.get(id=cohort_id, team__project_id=self.team.project_id)
        return HogQLCohortQuery(cohort=cohort, team=self.team).get_query()

    def embed_text(self, text: str, model: Optional[str] = None) -> list[float]:
        # Deferred: posthog.api pulls in the DRF/view universe; keep it off the import path.
        from posthog.api.embedding_worker import generate_embedding  # noqa: PLC0415

        return generate_embedding(self.team, text, model).embedding

    def restricted_properties(self) -> set[RestrictedProperty]:
        team_id = self._team_id if self._team_id is not None else self.team.id
        return get_restricted_properties_for_team(team_id=team_id, user=self._user)


def provider_for(team: Team, user: Optional["User"] = None) -> DataProvider:
    """Adapt a Django ``Team`` into the ``DataProvider`` the HogQL engine consumes.

    The single Team→provider construction point outside ``HogQLContext``'s lazy default.
    """
    return DjangoDataProvider(team=team, user=user)
