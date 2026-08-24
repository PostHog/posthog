"""DRF views for data quality checks, nested under the subjects they audit.

Checks hang off the existing warehouse surfaces -- ``warehouse_saved_queries/{id}/checks`` and
``warehouse_tables/{id}/checks`` -- the same way run/materialize/resume do, gated by warehouse
scopes rather than a scope of their own. Thin: validate via the serializer, call the facade,
serialize the result. Nothing here runs a check -- every trigger hands off to Temporal and returns
a suite-run handle to poll.
"""

from collections.abc import Callable
from typing import ClassVar, cast

from django.db.models import QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from ..facade import api
from ..facade.enums import CheckRunStatus, SubjectType
from ..facade.flags import is_data_quality_checks_enabled
from ..facade.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from .serializers import (
    CheckTypeSerializer,
    DataQualityCheckRunSerializer,
    DataQualityCheckSerializer,
    DataQualityGateConfigSerializer,
    DataQualitySuiteRunSerializer,
    SubjectHealthSerializer,
)

_RECENT_RUNS_LIMIT = 50


class _SubjectScopedViewSet(TeamAndOrgViewSetMixin):
    """Shared plumbing for viewsets nested under a warehouse saved query or table.

    Every entry point is gated on the product flag and on access to the parent subject -- the same
    name-based denial the information_schema loaders read, so REST and SQL can never disagree about
    which subjects a member may see. Most actions additionally require query access: run results are
    a count oracle over the underlying rows, so a member denied `query` must not reach them through
    a check. Only the check-type *catalog* stays ungated by query: static schema metadata.
    """

    team: Team
    subject_type: ClassVar[SubjectType]
    subject_field: ClassVar[str]
    QUERY_GATED_ACTIONS: ClassVar[frozenset[str]] = frozenset()

    @property
    def subject_uuid(self) -> str:
        return str(self.parents_query_dict[f"{self.subject_field}_id"])

    def initial(self, request: Request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        self._require_flag()
        if getattr(self, "action", None) in self.QUERY_GATED_ACTIONS:
            self._require_query_access()
        self._require_parent_subject_access()

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        # Token callers carry scopes but no RBAC, so the query gate has to be a scope for them.
        if getattr(view, "action", None) in self.QUERY_GATED_ACTIONS:
            return [f"{self.scope_object}:{'read' if request.method in SAFE_METHODS else 'write'}", "query:read"]
        # Everything else defers along the MRO, so the access-control actions this viewset inherits
        # keep demanding access_control:read rather than riding the warehouse scope alone.
        parent = getattr(super(), "dangerously_get_required_scopes", None)
        return parent(request, view) if parent is not None else None

    def _require_flag(self) -> None:
        if not is_data_quality_checks_enabled(self.team):
            raise PermissionDenied("Data quality checks are not enabled for this project.")

    def _require_query_access(self) -> None:
        # required_scopes gates tokens; session users carry no scopes and AccessControlPermission
        # only checks the warehouse resource, so enforce query RBAC explicitly too.
        if not self.user_access_control.check_access_level_for_resource("query", "viewer"):
            raise PermissionDenied("You need query access to work with data quality checks.")

    def _require_parent_subject_access(self) -> None:
        """403 a denied parent -- for every action, including list.

        A member denied a view must not be able to enumerate its check configs or counts through
        this surface. Orphan-tolerant rather than 404ing: a parent that no longer resolves still
        serves its checks (they are skipped, not hidden), because resolution carries no RBAC to
        enforce and orphaned history must stay reachable -- but only for a caller who cannot be
        object-denied, since an orphan has no name left to check a denial against.
        """
        ref = api.resolve_subject(self.team.id, self.subject_type, self.subject_uuid)
        if not ref.exists:
            # Deleting the subject takes its denial with it: the orphan resolves to an empty name,
            # and the denial set is rebuilt from the subjects that still exist, so neither can show
            # the caller was allowed this one. Without that proof, only a caller who cannot be
            # object-denied keeps orphan access.
            if self._can_be_object_denied():
                raise PermissionDenied("You don't have access to this table or view.")
            return
        if api.is_subject_denied(ref.name, self._denied_subject_names()):
            raise PermissionDenied("You don't have access to this table or view.")

    def _can_be_object_denied(self) -> bool:
        """Whether object-level warehouse denials can apply to this caller at all.

        False for an org admin, or an organization without access controls: neither can be denied a
        single table or view, so an empty denial set is proof of access rather than missing data.
        """
        uac = self.user_access_control
        return uac is not None and not uac.is_organization_admin and uac.access_controls_supported

    def _denied_subject_names(self) -> set[str]:
        # Same denial the information_schema loaders read. Computed once per request.
        cached = getattr(self, "_denied_subjects_cache", None)
        if cached is None:
            # A warehouse subject can only be denied to a non-admin in an org with access controls, so
            # skip the (heavy) database build otherwise -- the denied set would be empty either way,
            # which keeps this in lock-step with the loaders rather than diverging from them.
            if not self._can_be_object_denied():
                cached = set()
            else:
                try:
                    cached = api.denied_subject_names(
                        self.team,
                        cast(User, self.request.user),
                        user_access_control=self.user_access_control,
                    )
                except Exception as err:
                    # Building the denial set walks every saved query; one malformed definition must
                    # not 500 the surface. Failing open would leak denied subjects, so fail closed.
                    capture_exception(err)
                    raise PermissionDenied("Could not verify your access to this table or view.")
            self._denied_subjects_cache = cached
        return cached

    def _require_referenced_subject_access(self, check_type: str, config: dict) -> None:
        # The parent is not the only subject a check reads: a relationships check names a second
        # subject and a custom_sql query selects arbitrary tables, both run by the worker with team
        # scope only. Authorize them too, or a check on an allowed subject is a count oracle over a
        # denied one.
        denied = self._denied_subject_names()
        if not denied:
            return
        for name in api.referenced_subject_names(self.team.id, check_type, config):
            if api.is_subject_denied(name, denied):
                raise PermissionDenied("You don't have access to a table or view this check reads.")


class _BaseCheckViewSet(_SubjectScopedViewSet, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """CRUD for one subject's checks, plus the actions that run them and report on them."""

    QUERY_GATED_ACTIONS = frozenset(
        {"list", "retrieve", "create", "update", "partial_update", "destroy", "run", "run_all", "runs", "health"}
    )
    serializer_class = DataQualityCheckSerializer
    queryset = DataQualityCheck.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[DataQualityCheck]) -> QuerySet[DataQualityCheck]:
        # The parent lookup filters by the subject FK; deleted checks stay hidden.
        queryset = queryset.filter(team_id=self.team_id, deleted=False)
        if check_type := self.request.query_params.get("check_type"):
            queryset = queryset.filter(check_type=check_type)
        return queryset.order_by("-created_at")

    def get_serializer_context(self) -> dict:
        return {
            **super().get_serializer_context(),
            "subject_type": self.subject_type,
            "subject_uuid": self.subject_uuid,
        }

    @extend_schema(
        description="Create a check on this table or view, or refine the one already carrying the same "
        "fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self._require_referenced_subject_access(data["check_type"], data.get("config") or {})

        optional = {
            key: data[key]
            for key in (
                "name",
                "description",
                "severity",
                "enabled",
                "tags",
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
            subject_type=self.subject_type,
            subject_uuid=self.subject_uuid,
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
        # The parent gate cleared the declared subject; a check can still read a denied one
        # (relationships target, custom_sql table), so gate on every subject it references too.
        check = self.get_object()
        self._require_referenced_subject_access(check.check_type, check.config)
        # The subject is stamped alongside check_ids so the handle stays reachable through this
        # subject's nested suite-run routes, which filter on it. check_ids still decides what runs.
        suite_run = api.start_check_suite(
            team=self.team,
            user=cast(User, request.user),
            subject_type=self.subject_type,
            subject_uuids=[self.subject_uuid],
            check_ids=[str(check.id)],
        )
        return Response(DataQualitySuiteRunSerializer(suite_run).data)

    @extend_schema(
        description="Run every enabled check on this table or view. Returns the suite run to poll.",
        request=None,
        responses={200: DataQualitySuiteRunSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="run_all")
    def run_all(self, request: Request, **kwargs) -> Response:
        # Each of the subject's checks may read a further subject the member is denied, so gate on
        # those too before running the batch. Only a restricted member has anything to check.
        if self._denied_subject_names():
            for check in api.checks_for_subject(self.team_id, self.subject_type, self.subject_uuid).filter(
                enabled=True
            ):
                self._require_referenced_subject_access(check.check_type, check.config)
        suite_run = api.start_check_suite(
            team=self.team,
            user=cast(User, request.user),
            subject_type=self.subject_type,
            subject_uuids=[self.subject_uuid],
        )
        return Response(DataQualitySuiteRunSerializer(suite_run).data)

    @extend_schema(
        description="Recent run history for this check, newest first.",
        responses={200: DataQualityCheckRunSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True, pagination_class=None)
    def runs(self, request: Request, **kwargs) -> Response:
        check = self.get_object()
        self._require_referenced_subject_access(check.check_type, check.config)
        runs = DataQualityCheckRun.objects.for_team(self.team_id).filter(quality_check=check).order_by("-created_at")
        return Response(DataQualityCheckRunSerializer(runs[:_RECENT_RUNS_LIMIT], many=True).data)

    @extend_schema(
        description="Health rollup for this table or view, from the denormalized status of its checks.",
        responses={200: SubjectHealthSerializer},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def health(self, request: Request, **kwargs) -> Response:
        checks = api.checks_for_subject(self.team_id, self.subject_type, self.subject_uuid).filter(enabled=True)
        failing = checks.filter(last_status=CheckRunStatus.FAILED)
        return Response(
            SubjectHealthSerializer(
                {
                    "subject_type": self.subject_type,
                    "subject_uuid": self.subject_uuid,
                    "health": api.subject_health(self.team_id, self.subject_type, self.subject_uuid),
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
        return Response(CheckTypeSerializer(api.list_check_types(), many=True).data)


class SavedQueryCheckViewSet(_BaseCheckViewSet):
    scope_object = "warehouse_view"
    subject_type = SubjectType.VIEW
    subject_field = "saved_query"


class TableCheckViewSet(_BaseCheckViewSet):
    scope_object = "warehouse_table"
    subject_type = SubjectType.TABLE
    subject_field = "table"


class _BaseSuiteRunViewSet(
    _SubjectScopedViewSet,
    AccessControlViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only reports for this subject's check-suite executions."""

    QUERY_GATED_ACTIONS = frozenset({"list", "retrieve", "check_runs"})
    serializer_class = DataQualitySuiteRunSerializer
    queryset = DataQualitySuiteRun.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[DataQualitySuiteRun]) -> QuerySet[DataQualitySuiteRun]:
        # The parent lookup is rewritten onto subject_uuid, so this lists the parent's own
        # single-subject suites. Multi-subject sweep suites stay reachable through
        # information_schema, which is the cross-subject surface.
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    @extend_schema(
        description="Every check execution in this suite run.",
        responses={200: DataQualityCheckRunSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True, url_path="check_runs", pagination_class=None)
    def check_runs(self, request: Request, **kwargs) -> Response:
        suite_run = self.get_object()
        runs = DataQualityCheckRun.objects.for_team(self.team_id).filter(suite_run=suite_run).order_by("-created_at")
        return Response(DataQualityCheckRunSerializer(runs, many=True).data)


def _parent_id_parameter(name: str, description: str) -> Callable[[type], type]:
    # The suite-run model carries the parent as subject_uuid, so drf-spectacular cannot derive the
    # nested path parameter's type from a model field; annotate it on every action instead.
    parameter = OpenApiParameter(name, OpenApiTypes.UUID, OpenApiParameter.PATH, description=description)
    schema = extend_schema(parameters=[parameter])
    return extend_schema_view(list=schema, retrieve=schema, check_runs=schema)


@_parent_id_parameter("saved_query_id", "Id of the saved query whose suite runs these are.")
class SavedQuerySuiteRunViewSet(_BaseSuiteRunViewSet):
    scope_object = "warehouse_view"
    subject_type = SubjectType.VIEW
    subject_field = "saved_query"
    filter_rewrite_rules = {"saved_query_id": "subject_uuid"}


@_parent_id_parameter("table_id", "Id of the warehouse table whose suite runs these are.")
class TableSuiteRunViewSet(_BaseSuiteRunViewSet):
    scope_object = "warehouse_table"
    subject_type = SubjectType.TABLE
    subject_field = "table"
    filter_rewrite_rules = {"table_id": "subject_uuid"}


def data_quality_gate_response(team: Team, request: Request) -> Response:
    """GET/PATCH handler for the team's gate setting, mounted on the warehouse viewset.

    Lives here so the warehouse surface stays a thin mount: the flag gate, the serializer, and the
    config write all belong to this product.
    """
    if not is_data_quality_checks_enabled(team):
        raise PermissionDenied("Data quality checks are not enabled for this project.")
    if request.method == "PATCH":
        serializer = DataQualityGateConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        config = api.set_gate_materialization_on_checks(
            team, serializer.validated_data["gate_materialization_on_checks"]
        )
    else:
        config = api.get_gate_config(team)
    return Response(DataQualityGateConfigSerializer(config).data)
