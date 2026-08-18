"""DRF views for data quality checks.

Thin: validate via the serializer, call the facade, serialize the result. Nothing here runs a
check -- every trigger hands off to Temporal and returns a suite-run handle to poll.
"""

from typing import cast

from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import Team, User

from ..facade import api
from ..facade.enums import CheckRunStatus
from ..facade.flags import is_data_quality_checks_enabled
from ..facade.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from .serializers import (
    CheckTypeSerializer,
    DataQualityCheckRunSerializer,
    DataQualityCheckSerializer,
    DataQualitySuiteRunSerializer,
    RunForSubjectSerializer,
    SubjectHealthQuerySerializer,
    SubjectHealthSerializer,
)

_RECENT_RUNS_LIMIT = 50


class _DataQualityGateMixin:
    """Gate every entry point on the product flag, including the ones that never touch the queryset."""

    team: Team
    # Authoring a check writes HogQL a worker will execute, running one executes it now, and the
    # result columns are a count oracle over the underlying rows. Each needs query access on top of
    # data_quality access, or a member denied `query` reads warehouse data through a check.
    # Reading check *definitions* is not gated: that is schema metadata, already visible elsewhere.
    QUERY_GATED_ACTIONS: frozenset[str] = frozenset()

    def initial(self, request: Request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)  # type: ignore[misc]
        self._require_flag()
        if getattr(self, "action", None) in self.QUERY_GATED_ACTIONS:
            self._require_query_access()

    def _require_flag(self) -> None:
        if not is_data_quality_checks_enabled(self.team):
            raise PermissionDenied("Data quality checks are not enabled for this project.")

    def _require_query_access(self) -> None:
        # required_scopes gates tokens; session users carry no scopes and AccessControlPermission
        # only checks the data_quality resource, so enforce query RBAC explicitly too.
        if not self.user_access_control.check_access_level_for_resource("query", "viewer"):  # type: ignore[attr-defined]
            raise PermissionDenied("You need query access to work with data quality checks.")

    def _denied_subject_names(self) -> set[str]:
        # Same denial the information_schema loaders read, so the REST endpoint and system tables can
        # never disagree about which subjects a member may see. Computed once per request.
        cached = getattr(self, "_denied_subjects_cache", None)
        if cached is None:
            uac = self.user_access_control  # type: ignore[attr-defined]
            # A warehouse subject can only be denied to a non-admin in an org with access controls, so
            # skip the (heavy) database build otherwise -- the denied set would be empty either way,
            # which keeps this in lock-step with the loaders rather than diverging from them.
            if uac is None or uac.is_organization_admin or not uac.access_controls_supported:
                cached = set()
            else:
                cached = api.denied_subject_names(
                    self.team,
                    cast(User, self.request.user),  # type: ignore[attr-defined]
                    user_access_control=uac,
                )
            self._denied_subjects_cache = cached
        return cached

    def _require_subject_access(self, subject_type: str, subject_uuid: str) -> None:
        # A denied table still resolves (resolution carries no RBAC), so an orphaned subject -- one that
        # no longer exists -- is allowed through; only a live, denied subject is blocked.
        ref = api.resolve_subject(self.team.id, subject_type, subject_uuid)
        if ref.exists and api.is_subject_denied(ref.name, self._denied_subject_names()):
            raise PermissionDenied("You don't have access to this table or view.")

    def _require_referenced_subject_access(self, check_type: str, config: dict) -> None:
        # The declared subject is not the only one a check reads: a relationships check names a second
        # subject and a custom_sql query selects arbitrary tables, both run by the worker with team
        # scope only. Authorize them too, or a check on an allowed subject is a count oracle over a
        # denied one.
        denied = self._denied_subject_names()
        if not denied:
            return
        for name in api.referenced_subject_names(self.team.id, check_type, config):
            if api.is_subject_denied(name, denied):
                raise PermissionDenied("You don't have access to a table or view this check reads.")


class DataQualityCheckViewSet(_DataQualityGateMixin, TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for data quality checks, plus the actions that run them and report on them."""

    QUERY_GATED_ACTIONS = frozenset({"create", "update", "partial_update", "run", "run_for_subject", "runs"})
    scope_object = "data_quality"
    serializer_class = DataQualityCheckSerializer
    queryset = DataQualityCheck.objects.unscoped()

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        # Token callers carry scopes but no RBAC, so the query gate has to be a scope for them.
        if getattr(view, "action", None) in self.QUERY_GATED_ACTIONS:
            return [f"{self.scope_object}:{'read' if request.method in SAFE_METHODS else 'write'}", "query:read"]
        return None

    def safely_get_queryset(self, queryset: QuerySet[DataQualityCheck]) -> QuerySet[DataQualityCheck]:
        # Filter fields are named literally rather than unpacked from the request so an attacker
        # can't smuggle an arbitrary field name or relationship traversal into the ORM query.
        queryset = queryset.filter(team_id=self.team_id, deleted=False)
        if subject_type := self.request.query_params.get("subject_type"):
            queryset = queryset.filter(subject_type=subject_type)
        if subject_uuid := self.request.query_params.get("subject_uuid"):
            queryset = queryset.filter(subject_uuid=subject_uuid)
        if check_type := self.request.query_params.get("check_type"):
            queryset = queryset.filter(check_type=check_type)
        # Hide checks whose subject the member is denied: the row carries the compiled config and the
        # observed counts, a count oracle over rows they cannot read directly.
        if denied := self._denied_subject_names():
            blocked = {
                name
                for name in queryset.values_list("subject_name", flat=True).distinct()
                if api.is_subject_denied(name, denied)
            }
            if blocked:
                queryset = queryset.exclude(subject_name__in=blocked)
        return queryset.order_by("-created_at")

    @extend_schema(
        description="Create a check, or refine the one already carrying the same fingerprint. "
        "Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.",
        parameters=[
            OpenApiParameter("subject_type", str, description="Filter the list to 'table' or 'view' subjects."),
            OpenApiParameter("subject_uuid", str, description="Filter the list to one table or view."),
            OpenApiParameter("check_type", str, description="Filter the list to one check type."),
        ],
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self._require_subject_access(data["subject_type"], str(data["subject_uuid"]))
        self._require_referenced_subject_access(data["check_type"], data.get("config") or {})

        optional = {
            key: data[key]
            for key in (
                "name",
                "description",
                "severity",
                "enabled",
                "tags",
                "run_on_materialization",
                "schedule_interval_minutes",
                "created_source",
                "ai_model",
                "confidence",
                "reasoning",
            )
            if key in data
        }
        check, created = api.upsert_check(
            team=self.team,
            user=cast(User, request.user),
            subject_type=data["subject_type"],
            subject_uuid=str(data["subject_uuid"]),
            check_type=data["check_type"],
            column_name=data.get("column_name", ""),
            config=data.get("config") or {},
            **optional,
        )
        return Response(
            self.get_serializer(check).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def perform_destroy(self, instance: DataQualityCheck) -> None:
        api.soft_delete_check(instance)

    @extend_schema(
        description="Run this check now. Returns the suite run to poll for the report.",
        request=None,
        responses={200: DataQualitySuiteRunSerializer},
    )
    @action(methods=["POST"], detail=True)
    def run(self, request: Request, **kwargs) -> Response:
        # get_object() runs through safely_get_queryset, which already drops checks on a denied
        # subject -- so a denied check 404s here before we could reach the subject. A check whose
        # *declared* subject is allowed can still read a denied one (relationships target, custom_sql
        # table), so gate on every subject it references before running it.
        check = self.get_object()
        self._require_referenced_subject_access(check.check_type, check.config)
        suite_run = api.start_check_suite(team=self.team, user=cast(User, request.user), check_ids=[str(check.id)])
        return Response(DataQualitySuiteRunSerializer(suite_run).data)

    @extend_schema(
        description="Run every enabled check on a table or view. Returns the suite run to poll for the report.",
        request=RunForSubjectSerializer,
        responses={200: DataQualitySuiteRunSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="run_for_subject")
    def run_for_subject(self, request: Request, **kwargs) -> Response:
        serializer = RunForSubjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subject_type = serializer.validated_data["subject_type"]
        subject_uuid = str(serializer.validated_data["subject_uuid"])
        self._require_subject_access(subject_type, subject_uuid)
        # The subject's own checks may each read a further subject the member is denied, so gate on
        # those too before running the batch. Only a restricted member has anything to check, so skip
        # loading the checks otherwise.
        if self._denied_subject_names():
            for check in api.checks_for_subject(self.team_id, subject_type, subject_uuid).filter(enabled=True):
                self._require_referenced_subject_access(check.check_type, check.config)
        suite_run = api.start_check_suite(
            team=self.team,
            user=cast(User, request.user),
            subject_type=subject_type,
            subject_uuids=[subject_uuid],
        )
        return Response(DataQualitySuiteRunSerializer(suite_run).data)

    @extend_schema(
        description="Recent run history for this check, newest first.",
        responses={200: DataQualityCheckRunSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True, pagination_class=None)
    def runs(self, request: Request, **kwargs) -> Response:
        check = self.get_object()
        runs = DataQualityCheckRun.objects.for_team(self.team_id).filter(quality_check=check).order_by("-created_at")
        return Response(DataQualityCheckRunSerializer(runs[:_RECENT_RUNS_LIMIT], many=True).data)

    @extend_schema(
        description="Health rollup for one table or view, from the denormalized status of its checks.",
        parameters=[SubjectHealthQuerySerializer],
        responses={200: SubjectHealthSerializer},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def health(self, request: Request, **kwargs) -> Response:
        query = SubjectHealthQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        subject_type = query.validated_data["subject_type"]
        subject_uuid = str(query.validated_data["subject_uuid"])
        self._require_subject_access(subject_type, subject_uuid)

        checks = api.checks_for_subject(self.team_id, subject_type, subject_uuid).filter(enabled=True)
        failing = checks.filter(last_status=CheckRunStatus.FAILED)
        return Response(
            SubjectHealthSerializer(
                {
                    "subject_type": subject_type,
                    "subject_uuid": subject_uuid,
                    "health": api.subject_health(self.team_id, subject_type, subject_uuid),
                    "checks_total": checks.count(),
                    "checks_failing": failing.count(),
                }
            ).data
        )

    @extend_schema(
        description="The check types this project can author, with the JSON schema of each type's config.",
        responses={200: CheckTypeSerializer(many=True)},
    )
    @action(methods=["GET"], detail=False, url_path="check_types", pagination_class=None)
    def check_types(self, request: Request, **kwargs) -> Response:
        return Response(
            CheckTypeSerializer(
                [
                    {
                        "check_type": spec.type_name,
                        "description": getattr(spec, "description", ""),
                        "requires_column": spec.requires_column,
                        "config_schema": spec.json_schema,
                    }
                    for spec in api.all_specs()
                ],
                many=True,
            ).data
        )


class DataQualitySuiteRunViewSet(
    _DataQualityGateMixin,
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only reports for batches of check executions."""

    QUERY_GATED_ACTIONS = frozenset({"list", "retrieve", "check_runs"})
    scope_object = "data_quality"
    serializer_class = DataQualitySuiteRunSerializer
    queryset = DataQualitySuiteRun.objects.unscoped()

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        # Suite reports carry the counts a denied user must not be able to read.
        if getattr(view, "action", None) in self.QUERY_GATED_ACTIONS:
            return ["data_quality:read", "query:read"]
        return None

    def safely_get_queryset(self, queryset: QuerySet[DataQualitySuiteRun]) -> QuerySet[DataQualitySuiteRun]:
        queryset = queryset.filter(team_id=self.team_id)
        # A single-subject suite exposes that subject_uuid alongside its passed/failed/errored counts,
        # a per-subject outcome the member must not read for a denied table. Drop those runs, matching
        # how check_runs already hides denied child rows. Mixed-subject suites carry no subject_uuid,
        # so they surface no denied identifier; their child rows stay filtered by the check_runs action.
        if denied := self._denied_subject_names():
            blocked = self._denied_suite_subject_uuids(queryset, denied)
            if blocked:
                queryset = queryset.exclude(subject_uuid__in=blocked)
        return queryset.order_by("-created_at")

    def _denied_suite_subject_uuids(self, queryset: QuerySet[DataQualitySuiteRun], denied: set[str]) -> set[str]:
        # The suite row keeps subject_type + subject_uuid but not the name, so resolve each distinct
        # single-subject pair to the name the denial set is keyed by. Skipped entirely for the common
        # caller with an empty denied set, so the resolve loop only runs for a restricted member.
        blocked: set[str] = set()
        pairs = queryset.exclude(subject_uuid__isnull=True).values_list("subject_type", "subject_uuid").distinct()
        for subject_type, subject_uuid in pairs:
            ref = api.resolve_subject(self.team_id, subject_type, str(subject_uuid))
            if ref.exists and api.is_subject_denied(ref.name, denied):
                blocked.add(str(subject_uuid))
        return blocked

    @extend_schema(
        description="Every check execution in this suite run.",
        responses={200: DataQualityCheckRunSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True, url_path="check_runs", pagination_class=None)
    def check_runs(self, request: Request, **kwargs) -> Response:
        suite_run = self.get_object()
        runs: list[DataQualityCheckRun] = list(
            DataQualityCheckRun.objects.for_team(self.team_id).filter(suite_run=suite_run).order_by("-created_at")
        )
        # A suite run is not subject-scoped, so drop runs whose subject the member is denied -- each
        # carries the failed-row count and observed value.
        if denied := self._denied_subject_names():
            runs = [run for run in runs if not api.is_subject_denied(run.subject_name, denied)]
        return Response(DataQualityCheckRunSerializer(runs, many=True).data)
