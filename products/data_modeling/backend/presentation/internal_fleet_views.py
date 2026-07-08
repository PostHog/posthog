"""Cross-team (fleet) read-only internal API for the modeling-ops admin app.

Routes are wired manually in posthog/urls.py under ``api/internal/data_modeling_ops/``.
Contour must 403 that prefix at the edge before these deploy (charts PR); locally there
is no Contour so they are directly reachable against ./bin/start. Authenticated with
OIDC ID tokens — see internal_auth.py.
"""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team

from products.data_modeling.backend.facade.fleet_ops import (
    classify_migration,
    dag_ids_by_team,
    failing_saved_query_rows,
    find_duplicate_backing_tables,
    find_multi_dag_saved_queries,
    find_orphaned_schedules,
    find_unscheduled_entities,
    group_failing_by_schedule,
    list_data_modeling_schedules,
    modeling_team_ids,
    team_activity_rows,
)
from products.data_modeling.backend.facade.schedule_truth import SCHEDULE_CANDIDATE_CAP, describe_schedules
from products.data_modeling.backend.presentation.internal_auth import DataModelingOpsAuthenticationMixin
from products.data_modeling.backend.presentation.internal_serializers import (
    InternalDuplicateBackingTableGroupSerializer,
    InternalFailingScheduleGroupSerializer,
    InternalFleetTeamSerializer,
    InternalMigrationMatrixRowSerializer,
    InternalMultiDagSavedQuerySerializer,
    InternalOrphanedScheduleSerializer,
    InternalUnscheduledEntitySerializer,
)
from products.data_modeling.backend.presentation.internal_views import _is_v2_backend_enabled_for_team

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100


def _page_params(request: Request) -> tuple[int, int]:
    try:
        limit = min(int(request.query_params.get("limit", DEFAULT_PAGE_LIMIT)), MAX_PAGE_LIMIT)
        offset = max(int(request.query_params.get("offset", 0)), 0)
    except ValueError:
        return DEFAULT_PAGE_LIMIT, 0
    return max(limit, 1), offset


def _teams_by_id(team_ids: list[int]) -> dict[int, Team]:
    return {team.id: team for team in Team.objects.filter(id__in=team_ids)}


class InternalDataModelingOpsFleetViewSet(
    DataModelingOpsAuthenticationMixin, TeamAndOrgViewSetMixin, viewsets.GenericViewSet
):
    """Cross-team read-only endpoints for the modeling-ops admin app.

    Authenticated with OIDC ID tokens only (no session/PAT/OAuth fallback); not exposed
    through Contour ingress.
    """

    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    @extend_schema(exclude=True)
    def internal_teams(self, request: Request, **kwargs: Any) -> Response:
        limit, offset = _page_params(request)
        all_team_ids = modeling_team_ids()
        page_ids = all_team_ids[offset : offset + limit]
        rows = team_activity_rows(page_ids)
        teams = _teams_by_id(page_ids)
        for team_id, row in rows.items():
            team = teams.get(team_id)
            row["team_name"] = team.name if team else None
            row["organization_id"] = str(team.organization_id) if team else None
        serializer = InternalFleetTeamSerializer([rows[team_id] for team_id in page_ids], many=True)
        return Response({"results": serializer.data, "count": len(all_team_ids), "limit": limit, "offset": offset})

    @extend_schema(exclude=True)
    def internal_migration_matrix(self, request: Request, **kwargs: Any) -> Response:
        limit, offset = _page_params(request)
        team_ids_param = request.query_params.get("team_ids")
        if team_ids_param:
            try:
                all_team_ids: list[int] = sorted({int(value) for value in team_ids_param.split(",")})
            except ValueError:
                return Response({"error": "team_ids must be a comma-separated list of integers"}, status=400)
        else:
            all_team_ids = modeling_team_ids()
        page_ids = all_team_ids[offset : offset + limit]

        rows = team_activity_rows(page_ids)
        teams = _teams_by_id(page_ids)
        dag_ids = dag_ids_by_team(page_ids)

        # Describe candidate DAG schedules individually — independent of the
        # search-attribute backfill state, same trade-off as the team schedules route.
        all_dag_ids = [dag_id for ids in dag_ids.values() for dag_id in ids]
        truncated = len(all_dag_ids) > SCHEDULE_CANDIDATE_CAP
        temporal_error: str | None = None
        try:
            descriptions = describe_schedules(all_dag_ids[:SCHEDULE_CANDIDATE_CAP])
        except Exception as error:
            # Switches A and C are DB/flag facts; keep them visible and null out B.
            descriptions = {}
            temporal_error = str(error)
        v2_scheduled_dag_ids = {
            schedule_id for schedule_id, info in descriptions.items() if info is not None and info["kind"] == "v2_dag"
        }

        results = []
        for team_id in page_ids:
            team = teams.get(team_id)
            switch_a = _is_v2_backend_enabled_for_team(team) if team else False
            switch_b: bool | None = (
                None if temporal_error else any(dag_id in v2_scheduled_dag_ids for dag_id in dag_ids[team_id])
            )
            switch_c_remaining = rows[team_id]["saved_queries_with_sync_frequency_count"]
            results.append(
                {
                    "team_id": team_id,
                    "team_name": team.name if team else None,
                    "switch_a_v2_flag_enabled": switch_a,
                    "switch_b_v2_schedule_present": switch_b,
                    "switch_c_sync_frequencies_remaining": switch_c_remaining,
                    "dag_count": rows[team_id]["dag_count"],
                    # Without switch B (Temporal down) any label would be a guess.
                    "classification": (
                        classify_migration(
                            has_dags=bool(dag_ids[team_id]),
                            v2_flag_enabled=switch_a,
                            v2_schedule_present=switch_b,
                            sync_frequencies_remaining=switch_c_remaining,
                        )
                        if switch_b is not None
                        else None
                    ),
                }
            )
        serializer = InternalMigrationMatrixRowSerializer(results, many=True)
        return Response(
            {
                "results": serializer.data,
                "count": len(all_team_ids),
                "limit": limit,
                "offset": offset,
                "truncated": truncated,
                "temporal_error": temporal_error,
            }
        )

    @extend_schema(exclude=True)
    def internal_orphans(self, request: Request, **kwargs: Any) -> Response:
        direction = request.query_params.get("direction", "both")
        if direction not in ("schedules", "entities", "both"):
            return Response({"error": "direction must be one of schedules, entities, both"}, status=400)

        try:
            schedules = list_data_modeling_schedules()
        except Exception as error:
            # Orphan detection is meaningless without the Temporal listing.
            return Response({"error": f"Temporal unreachable: {error}"}, status=503)
        payload: dict[str, Any] = {"schedule_count": len(schedules)}
        if direction in ("schedules", "both"):
            payload["schedules_without_entity"] = InternalOrphanedScheduleSerializer(
                find_orphaned_schedules(schedules), many=True
            ).data
        if direction in ("entities", "both"):
            unscheduled, scan_capped = find_unscheduled_entities(schedules)
            payload["entities_without_schedule"] = InternalUnscheduledEntitySerializer(unscheduled, many=True).data
            payload["unscheduled_scan_capped"] = scan_capped
        return Response(payload)

    @extend_schema(exclude=True)
    def internal_failing_schedules(self, request: Request, **kwargs: Any) -> Response:
        rows = failing_saved_query_rows()
        temporal_error: str | None = None
        try:
            schedules = list_data_modeling_schedules()
        except Exception as error:
            # Failure rows come from the DB; degrade to an 'unscheduled' grouping rather
            # than hiding failing models behind a Temporal outage.
            schedules = []
            temporal_error = str(error)
        groups = group_failing_by_schedule(rows, schedules)
        serializer = InternalFailingScheduleGroupSerializer(groups, many=True)
        return Response(
            {
                "results": serializer.data,
                "failing_saved_query_count": len(rows),
                "temporal_error": temporal_error,
            }
        )

    @extend_schema(exclude=True)
    def internal_duplicates(self, request: Request, **kwargs: Any) -> Response:
        return Response(
            {
                "multi_dag_saved_queries": InternalMultiDagSavedQuerySerializer(
                    find_multi_dag_saved_queries(), many=True
                ).data,
                "duplicate_backing_tables": InternalDuplicateBackingTableGroupSerializer(
                    find_duplicate_backing_tables(), many=True
                ).data,
            }
        )
