"""DRF views for data quality checks.

Every check is authored, read, run and scheduled through ``data_quality_checks``, whatever kind of
subject it audits. The subject is named in the body on create and read off the check row after
that. Thin: validate via the serializer, call the facade, serialize the result. Nothing here runs a
check -- every trigger hands off to Temporal and returns a suite-run handle to poll.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, cast
from uuid import UUID

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import Team, User
from posthog.permissions import APIScopePermission, TeamMemberAccessPermission, get_authenticator_scopes
from posthog.rate_limit import HogQLQueryThrottle

from ..facade import api
from ..facade.enums import CheckRunStatus, CheckType, SubjectStatus, SubjectType
from ..facade.flags import is_data_quality_checks_enabled
from ..facade.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from .serializers import (
    CheckTypeSerializer,
    DataQualityCheckCreateSerializer,
    DataQualityCheckRunSerializer,
    DataQualityCheckScheduleSerializer,
    DataQualityCheckScheduleUpdateSerializer,
    DataQualityCheckSerializer,
    DataQualityGateConfigSerializer,
    DataQualityMetricSubjectSerializer,
    DataQualityOutputSchemaSerializer,
    DataQualityOverviewCheckSerializer,
    DataQualityRunRequestSerializer,
    DataQualitySubjectRefSerializer,
    DataQualitySubjectScheduleSerializer,
    DataQualitySubjectSerializer,
    DataQualitySuiteRunSerializer,
    SubjectHealthSerializer,
)

_RECENT_RUNS_LIMIT = 50
_LAST_RUN_FIELDS = ("last_status", "last_run_at", "last_succeeded_at", "failing_since")
_SUBJECT_TYPE_VALUES = frozenset(kind.value for kind in SubjectType)

if TYPE_CHECKING:
    from rest_framework.permissions import _SupportsHasPermission


class _DataQualitySubjectPermission(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        if not isinstance(view, _QualityGatedViewSet):
            return False
        if not view.user_access_control.check_access_level_for_object(view.team, "member"):
            return False
        return bool(view._authorized_subject_types(write=request.method not in SAFE_METHODS))

    def has_object_permission(self, request: Request, view: APIView, obj: object) -> bool:
        return (
            isinstance(view, _QualityGatedViewSet)
            and isinstance(obj, DataQualityCheck | DataQualitySuiteRun)
            and obj.team_id == view.team_id
            and self.has_permission(request, view)
        )


class _QualityGatedViewSet(TeamAndOrgViewSetMixin):
    """The gating every data quality surface shares.

    Entry points are gated on the product flag and on query access: run results are a count oracle
    over the underlying rows, so a member denied `query` must not reach them through a check. Only
    the check-type *catalog* stays ungated by any one subject: it is static schema metadata.

    Denial is name-based, reading the same set the information_schema loaders do, so REST and SQL
    can never disagree about which subjects a member may see.
    """

    team: Team
    QUERY_GATED_ACTIONS: ClassVar[frozenset[str]] = frozenset()

    def dangerously_get_permissions(self) -> list["_SupportsHasPermission"]:
        if self.action not in self.QUERY_GATED_ACTIONS:
            raise NotImplementedError()
        return [
            IsAuthenticated(),
            APIScopePermission(),
            TeamMemberAccessPermission(),
            _DataQualitySubjectPermission(),
            *(permission() for permission in self.permission_classes),
        ]

    def _filter_queryset_by_access_level(self, queryset: QuerySet) -> QuerySet:
        # Checks and suite runs answer to the subject gate rather than the generic object filter, so
        # both bypass it. A check is filtered by visible_check_queryset, which every listing path
        # routes through and which applies the subject predicate itself; a suite run is filtered here.
        if self.action != "list" or queryset.model not in (DataQualityCheck, DataQualitySuiteRun):
            return super()._filter_queryset_by_access_level(queryset)
        if queryset.model is DataQualityCheck or not self._can_be_object_denied():
            return queryset
        context = self._denial_context()
        return queryset.exclude(api.unreadable_suites_q(context)).exclude(
            api.suites_backing_unreadable_runs_q(self.team_id, context)
        )

    def initial(self, request: Request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        self._require_flag()
        if getattr(self, "action", None) in self.QUERY_GATED_ACTIONS:
            self._require_query_access()

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

    @cached_property
    def _authorized_types(self) -> dict[bool, frozenset[SubjectType]]:
        return {}

    @cached_property
    def _definition_verdicts(self) -> dict[str, bool]:
        return {}

    @cached_property
    def _metric_subjects(self) -> dict[UUID, api.SubjectRef]:
        return {}

    def _authorized_subject_types(self, *, write: bool = False) -> frozenset[SubjectType]:
        if write not in self._authorized_types:
            self._authorized_types[write] = api.authorized_subject_types(
                self.user_access_control,
                get_authenticator_scopes(self.request.successful_authenticator),
                write=write,
            )
        return self._authorized_types[write]

    @cached_property
    def _writable_subjects(self) -> api.ReadableSubjects:
        return api.writable_subjects(
            self._denial_context(), self.user_access_control, allowed=self._authorized_subject_types(write=True)
        )

    def _can_be_object_denied(self) -> bool:
        # Shared with the information_schema loaders, so the two surfaces agree on which callers a
        # gate applies to as well as on what it decides.
        return api.can_be_object_denied(self.user_access_control) or self._authorized_subject_types() != frozenset(
            SubjectType
        )

    def _denial_context(self) -> api.DenialContext:
        """The subjects this caller may read, and the names they are denied. Once per request.

        Only ever called behind ``_can_be_object_denied``: for anyone else there is nothing to
        decide, and the snapshot is not cheap enough to build for them.
        """
        cached = getattr(self, "_denial_context_cache", None)
        if cached is None:
            cached = api.restrict_subject_types(
                api.caller_denial_context(
                    self.team,
                    cast(User, self.request.user),
                    user_access_control=self.user_access_control,
                ),
                self._authorized_subject_types(),
            )
            self._denial_context_cache = cached
        return cached

    def _hidden_check_ids(self, checks: list[DataQualityCheck]) -> set[UUID]:
        # The same rule the information_schema loaders apply, so REST and SQL cannot come to
        # different answers about the same check.
        visible = api.visible_checks(self.team_id, checks, self._denial_context())
        return {check.id for check in checks} - {check.id for check in visible}

    def _unnamable_check_ids(self, runs: Sequence[DataQualityCheckRun]) -> set[UUID]:
        # A run is judged by the identities it recorded, but the name on its check is present tense.
        # Withhold the name of a check that is out of reach today, even where the run it left behind
        # stays readable on its own terms.
        if not self._can_be_object_denied():
            return set()
        checks = {run.quality_check.id: run.quality_check for run in runs if run.quality_check}
        return self._hidden_check_ids(list(checks.values()))

    def _readable_runs(self, runs: QuerySet[DataQualityCheckRun]) -> QuerySet[DataQualityCheckRun]:
        # Excluded in SQL rather than per page, so a run that read a subject out of reach is gone
        # before the window that bounds what is served.
        if not self._can_be_object_denied():
            return runs
        return api.without_denied_runs(runs, self._denial_context())

    def _require_referenced_subject_access(
        self, check_type: str, config: dict, *, subject: api.SubjectIdentity | None = None
    ) -> None:
        """403 a definition that reads a subject the caller cannot be shown to be allowed.

        The parent is not the only subject a check reads: a relationships check names a second
        subject and a custom_sql query selects arbitrary tables, both run by the worker with team
        scope only. Authorize them too, or a check on an allowed subject is a count oracle over a
        denied one.

        The verdict is a pure function of the definition, so a page or a suite that carries the same
        one many times parses and resolves it once.
        """
        if not self._can_be_object_denied():
            return
        resolved = self._definition_subject(subject) if subject is not None else None
        if api.memoized_definition_verdict(
            self.team_id, check_type, config, self._denial_context(), self._definition_verdicts, resolved
        ):
            raise PermissionDenied("You don't have access to a table or view this check reads.")

    def _definition_subject(self, identity: api.SubjectIdentity) -> api.SubjectRef | None:
        if identity.subject_type != SubjectType.METRIC:
            return None
        identifier = UUID(identity.subject_uuid)
        if identifier not in self._metric_subjects:
            self._metric_subjects.update(api.resolve_metric_subjects(self.team_id, [identifier]))
        return self._metric_subjects[identifier]

    @staticmethod
    def _check_identity(check: DataQualityCheck) -> api.SubjectIdentity | None:
        if check.subject_uuid is None:
            return None
        return api.SubjectIdentity(subject_type=check.subject_type, subject_uuid=str(check.subject_uuid))

    def _require_subject_access(self, identity: api.SubjectIdentity, *, write: bool) -> None:
        """403 a subject this caller may not read, or may not change when the request changes it.

        A subject that no longer resolves is out of reach on the same terms: deleting it takes its
        denial with it, so nothing left can show the caller was allowed it. A caller who cannot be
        object-denied keeps orphan access, since orphaned history stays reachable for them.
        """
        if not self._can_be_object_denied():
            return
        if not self._denial_context().readable.contains(identity.subject_type, identity.subject_uuid):
            raise PermissionDenied("You don't have access to this table or view.")
        if write and not self._writable_subjects.contains(identity.subject_type, identity.subject_uuid):
            raise PermissionDenied("You need edit access to this subject to change or run its checks.")

    def _require_subject_type_authorized(self, subject_type: str, *, write: bool) -> None:
        """403 a kind of subject this caller's role or token scopes do not cover at all."""
        if subject_type not in self._authorized_subject_types(write=write):
            raise PermissionDenied("You don't have permission to work with checks on this kind of subject.")

    def _require_subject(self, identity: api.SubjectIdentity, *, write: bool) -> None:
        self._require_subject_type_authorized(identity.subject_type, write=write)
        self._require_subject_access(identity, write=write)

    def _named_subject(self, source: Mapping[str, Any]) -> api.SubjectIdentity:
        """The subject this request names, as a 400 rather than a lookup when it names none."""
        serializer = DataQualitySubjectRefSerializer(data={key: source.get(key) for key in _SUBJECT_KEYS})
        serializer.is_valid(raise_exception=True)
        return api.SubjectIdentity(
            subject_type=str(serializer.validated_data["subject_type"]),
            subject_uuid=str(serializer.validated_data["subject_uuid"]),
        )

    def _optional_subject(self, source: Mapping[str, Any]) -> api.SubjectIdentity | None:
        if not any(source.get(key) for key in _SUBJECT_KEYS):
            return None
        return self._named_subject(source)

    def _require_enabled_check_access(self, identity: api.SubjectIdentity) -> None:
        """403 when any check the request is about to set running reads a subject out of reach."""
        if not self._can_be_object_denied():
            return
        for check in api.checks_for_subject(self.team_id, identity.subject_type, identity.subject_uuid).filter(
            enabled=True
        ):
            self._require_referenced_subject_access(check.check_type, check.config, subject=identity)


class ScheduleUnavailableAPIError(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "schedule_unavailable"
    default_detail = "Could not read or update the check schedule. Reload it and try again."


class _ProjectQualityViewSet(_QualityGatedViewSet):
    scope_object = "query"

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str]:
        return ["query:read"]

    def initial(self, request: Request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        if not self._authorized_subject_types(write=request.method not in SAFE_METHODS):
            raise PermissionDenied("You need access to warehouse objects or the data catalog to work with checks.")


_EDIT_DESCRIPTION = (
    "Edit this check in place, including what it asserts (check_type, column_name, config). The "
    "subject it audits is fixed, and the check keeps its id, run history, latest status, and latest "
    "run time. A definition or name already held by another active check comes back as a field "
    "error, with nothing written."
)

_SUBJECT_TYPE_PARAMETER = OpenApiParameter(
    "subject_type",
    OpenApiTypes.STR,
    OpenApiParameter.QUERY,
    enum=[kind.value for kind in SubjectType],
    description="Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.",
)
_SUBJECT_UUID_PARAMETER = OpenApiParameter(
    "subject_uuid",
    OpenApiTypes.UUID,
    OpenApiParameter.QUERY,
    description="Id of the table, view, metric, or PostHog table.",
)
_SUBJECT_PARAMETERS = [_SUBJECT_TYPE_PARAMETER, _SUBJECT_UUID_PARAMETER]
# A listing filter can be left out; a lookup cannot answer without a subject at all, so the actions
# that look one up declare both as required rather than letting a generated client omit them.
_REQUIRED_SUBJECT_PARAMETERS = [
    OpenApiParameter(
        parameter.name,
        parameter.type,
        parameter.location,
        required=True,
        description=parameter.description,
        enum=parameter.enum,
    )
    for parameter in _SUBJECT_PARAMETERS
]
_CHECK_TYPE_PARAMETER = OpenApiParameter(
    "check_type",
    OpenApiTypes.STR,
    OpenApiParameter.QUERY,
    enum=[kind.value for kind in CheckType],
    description="Only the checks that make this assertion. See /check_types/.",
)
_SUBJECT_KEYS = ("subject_type", "subject_uuid")


@extend_schema_view(
    update=extend_schema(description=_EDIT_DESCRIPTION),
    partial_update=extend_schema(description=_EDIT_DESCRIPTION),
    list=extend_schema(
        description="Every check in the project. Narrow it to one subject with subject_type and "
        "subject_uuid, or to one assertion with check_type.",
        parameters=[*_SUBJECT_PARAMETERS, _CHECK_TYPE_PARAMETER],
    ),
)
class DataQualityCheckViewSet(_ProjectQualityViewSet, viewsets.ModelViewSet):
    """Every check in the project: authoring, running, results, health, and schedules."""

    DETAIL_VISIBILITY_ACTIONS = frozenset({"retrieve", "destroy"})
    QUERY_GATED_ACTIONS = frozenset(
        {
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "run",
            "runs",
            "health",
            "output_schema",
            "schedule",
            "subjects",
            "metric_subjects",
        }
    )
    SUBJECT_FILTERED_ACTIONS = frozenset({"list", "health", "schedules"})
    serializer_class = DataQualityCheckSerializer
    queryset = DataQualityCheck.objects.unscoped()

    ACTION_SERIALIZERS: ClassVar[dict[str, type[BaseSerializer]]] = {
        "list": DataQualityOverviewCheckSerializer,
        "create": DataQualityCheckCreateSerializer,
    }

    def get_serializer_class(self) -> type[BaseSerializer]:
        return self.ACTION_SERIALIZERS.get(self.action or "", DataQualityCheckSerializer)

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str]:
        if getattr(view, "action", None) == "metric_subjects":
            return ["data_catalog:read", "query:read"]
        return super().dangerously_get_required_scopes(request, view)

    def _authorized_query_subject(self) -> api.SubjectIdentity | None:
        subject = self._optional_subject(self.request.query_params)
        if subject is not None:
            self._require_subject(subject, write=False)
        return subject

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        subject = getattr(self, "_authorized_subject", None)
        if subject is not None:
            context |= {"subject_type": subject.subject_type, "subject_uuid": subject.subject_uuid}
        return context

    def safely_get_queryset(self, queryset: QuerySet[DataQualityCheck]) -> QuerySet[DataQualityCheck]:
        # Orphans are excluded: their subject is gone, so there is no page to link to, nothing to
        # run, and no rollup to sit under. The run history they left behind stays queryable.
        # The rollup reads four columns of every enabled check in the project and serializes none of
        # the people, so it does not pay for the author join the listing needs.
        # A name is optional, so the id breaks the tie a blank one leaves -- newest first, and a
        # total order, without which two pages of the same listing can repeat or drop a check.
        queryset = (
            api.live_subject_checks(queryset.filter(team_id=self.team_id, deleted=False))
            .exclude(subject_status=SubjectStatus.ORPHANED)
            .order_by("subject_name", "name", "-id")
        )
        if self.action in self.SUBJECT_FILTERED_ACTIONS and (subject := self._authorized_query_subject()):
            queryset = queryset.filter(**api.subject_filter(subject.subject_type, subject.subject_uuid))
        if check_type := self.request.query_params.get("check_type"):
            queryset = queryset.filter(check_type=check_type)
        return queryset.select_related("created_by", "owner") if self.action == "list" else queryset

    def filter_queryset(self, queryset: QuerySet[DataQualityCheck]) -> QuerySet[DataQualityCheck]:
        # Hiding a denied subject's checks matters here: this one lists everything, so a leak is a
        # directory of the tables a member cannot read. Denial is matched by name rather than
        # equality, so the pass has to happen in Python; only a restricted member pays for it, since
        # the denied set is empty for everyone else.
        queryset = super().filter_queryset(queryset)
        if self.action not in self.SUBJECT_FILTERED_ACTIONS or not self._can_be_object_denied():
            return queryset
        return api.visible_check_queryset(self.team_id, queryset, self._denial_context())

    def list(self, request: Request, *args, **kwargs) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        checks = list(queryset) if page is None else page
        # Resolved once for the page, so linking to a subject costs two queries rather than one per
        # check. Anything the batch cannot resolve stays absent and renders as plain text.
        context = {**self.get_serializer_context(), "subject_locations": api.subject_locations(self.team_id, checks)}
        serializer = self.get_serializer(checks, many=True, context=context)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    def safely_get_object(self, queryset: QuerySet[DataQualityCheck]) -> DataQualityCheck:
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        check = get_object_or_404(queryset, **{self.lookup_field: self.kwargs[lookup_url_kwarg]})
        if (
            self.action in self.DETAIL_VISIBILITY_ACTIONS
            and self._can_be_object_denied()
            and check.id in self._hidden_check_ids([check])
        ):
            raise PermissionDenied("You don't have access to a table or view this check reads.")
        subject = self._check_identity(check)
        if subject is not None:
            self._require_subject(subject, write=self.request.method not in SAFE_METHODS)
        return check

    @extend_schema(
        description="Create a check on the table, view or metric named by subject_type and subject_uuid, "
        "or refine the one already carrying the same fingerprint. Re-creating a semantically identical "
        "check returns 200 and the existing row, never a duplicate.",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        subject = self._named_subject(request.data)
        self._require_subject(subject, write=True)
        self._authorized_subject = subject

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self._require_referenced_subject_access(data["check_type"], data.get("config") or {}, subject=subject)

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
            subject_type=subject.subject_type,
            subject_uuid=subject.subject_uuid,
            check_type=data["check_type"],
            column_name=data.get("column_name", ""),
            config=data.get("config") or {},
            **optional,
        )
        # A create can land on a check that already exists, whose last run read a subject this
        # caller is denied. Blank that run the way an edit does, or the fingerprint match becomes
        # the one way to read history that list hides, retrieve 403s and runs/ empties.
        if not created and self._last_run_is_hidden(check):
            self._redact_last_run(check)
        return Response(
            self.get_serializer(check).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def _last_run_is_hidden(self, check: DataQualityCheck) -> bool:
        return self._can_be_object_denied() and check.id in self._hidden_check_ids([check])

    @staticmethod
    def _redact_last_run(check: DataQualityCheck) -> None:
        for field in _LAST_RUN_FIELDS:
            setattr(check, field, None)

    def perform_update(self, serializer: BaseSerializer) -> None:
        serializer.context["authorize_check_edit"] = lambda current: self._authorize_check_edit(
            current, serializer.validated_data
        )
        updated_check = cast(DataQualityCheck, serializer.save())
        if self._last_run_is_hidden(updated_check):
            self._redact_last_run(updated_check)

    def _authorize_check_edit(self, check: DataQualityCheck, changes: dict) -> None:
        subject = self._check_identity(check)
        self._require_referenced_subject_access(check.check_type, check.config or {}, subject=subject)
        # The candidate definition, not the stored one: an edit that points the check at a new
        # relationships target or rewrites its custom SQL has to clear that subject too, before it
        # is saved and the worker starts running it.
        self._require_referenced_subject_access(
            changes.get("check_type", check.check_type),
            changes.get("config", check.config) or {},
            subject=subject,
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
        # The subject gate cleared the declared subject; a check can still read a denied one
        # (relationships target, custom_sql table), so gate on every subject it references too.
        check = self.get_object()
        subject = self._check_identity(check)
        self._require_referenced_subject_access(check.check_type, check.config, subject=subject)
        # The subject is stamped alongside check_ids so the suite reads back as scoped to it.
        # check_ids still decides what runs.
        suite_run = api.start_check_suite(
            team=self.team,
            user=cast(User, request.user),
            subject_type=subject.subject_type if subject else "",
            subject_uuids=[subject.subject_uuid] if subject else [],
            check_ids=[str(check.id)],
        )
        return Response(DataQualitySuiteRunSerializer(suite_run).data)

    @extend_schema(
        description="Recent run history for this check, newest first.",
        responses={200: DataQualityCheckRunSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True, pagination_class=None)
    def runs(self, request: Request, **kwargs) -> Response:
        check = self.get_object()
        # The current definition gates the check itself; each run is then judged on the definition
        # it executed, so editing a check into a harmless one does not unlock what it used to read.
        self._require_referenced_subject_access(check.check_type, check.config, subject=self._check_identity(check))
        runs = self._readable_runs(
            DataQualityCheckRun.objects.for_team(self.team_id).filter(quality_check=check)
        ).select_related("quality_check")
        return Response(
            DataQualityCheckRunSerializer(list(runs.order_by("-created_at")[:_RECENT_RUNS_LIMIT]), many=True).data
        )

    @extend_schema(
        description="Health rollup per subject, for every subject in the project that has checks. "
        "Narrow it to one subject with subject_type and subject_uuid.",
        parameters=_SUBJECT_PARAMETERS,
        responses={200: SubjectHealthSerializer(many=True)},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def health(self, request: Request, **kwargs) -> Response:
        # Rolled up from the checks already loaded, using the same rule as the listing. Calling
        # subject_health() per subject would be a query per table.
        by_subject: dict[tuple[str, str], list[DataQualityCheck]] = defaultdict(list)
        for check in self.filter_queryset(self.get_queryset()).filter(enabled=True):
            if check.subject_uuid is None:
                # An orphan has no subject left to roll up under.
                continue
            by_subject[(check.subject_type, str(check.subject_uuid))].append(check)

        rollups = [
            {
                "subject_type": subject_type,
                "subject_uuid": subject_uuid,
                "health": api.roll_up_health(
                    api.CheckStatusRow(severity=check.severity, last_status=check.last_status) for check in checks
                ),
                "checks_total": len(checks),
                "checks_failing": sum(1 for check in checks if check.last_status == CheckRunStatus.FAILED),
            }
            for (subject_type, subject_uuid), checks in by_subject.items()
        ]
        return Response(SubjectHealthSerializer(rollups, many=True).data)

    @extend_schema(
        description="The check types this project can author, with the JSON schema of each type's config. "
        "Pass subject_type to narrow it to the types that kind of subject supports.",
        parameters=[_SUBJECT_TYPE_PARAMETER],
        responses={200: CheckTypeSerializer(many=True)},
    )
    @action(methods=["GET"], detail=False, url_path="check_types", pagination_class=None)
    def check_types(self, request: Request, **kwargs) -> Response:
        subject_type = request.query_params.get("subject_type") or None
        if subject_type is not None and subject_type not in _SUBJECT_TYPE_VALUES:
            raise ValidationError({"subject_type": f"Unknown subject type '{subject_type}'."})
        return Response(CheckTypeSerializer(api.list_check_types(subject_type), many=True).data)

    @extend_schema(
        description="Everything in this project you can author a check on, with each subject's columns.",
        request=None,
        responses={200: DataQualitySubjectSerializer(many=True)},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def subjects(self, request: Request, **kwargs) -> Response:
        selectable = api.selectable_subjects(self.team_id, self._authorized_subject_types())
        editable_kinds = self._authorized_subject_types(write=True)
        if self._can_be_object_denied():
            readable = self._denial_context().readable
            writable = self._writable_subjects
            selectable = [
                replace(subject, editable=writable.contains(subject.subject_type, subject.id))
                for subject in selectable
                if readable.contains(subject.subject_type, subject.id)
            ]
        else:
            selectable = [
                replace(subject, editable=SubjectType(subject.subject_type) in editable_kinds) for subject in selectable
            ]
        return Response(DataQualitySubjectSerializer(selectable, many=True).data)

    @extend_schema(request=None, responses={200: DataQualityMetricSubjectSerializer(many=True)})
    @action(methods=["GET"], detail=False, pagination_class=None)
    def metric_subjects(self, request: Request, **kwargs) -> Response:
        if not self.user_access_control.check_access_level_for_resource("data_catalog", "viewer"):
            raise PermissionDenied("You need data catalog access to create checks on metrics.")
        metrics = api.testable_metric_subjects(self.team_id)
        if self._can_be_object_denied():
            readable_ids = self._denial_context().readable.metric_ids
            metrics = [metric for metric in metrics if metric.id in readable_ids]
        return Response(DataQualityMetricSubjectSerializer(metrics, many=True).data)

    @extend_schema(
        description="Columns the subject's query returns, for authoring a check against them. Metrics only.",
        parameters=_SUBJECT_PARAMETERS,
        request=None,
        responses={200: DataQualityOutputSchemaSerializer},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="output_schema",
        pagination_class=None,
        throttle_classes=[HogQLQueryThrottle],
    )
    def output_schema(self, request: Request, **kwargs) -> Response:
        subject = self._named_subject(request.query_params)
        self._require_subject(subject, write=False)
        if subject.subject_type != SubjectType.METRIC:
            raise ValidationError({"subject_type": "Only a metric has an output schema to read."})
        try:
            columns = api.metric_output_schema(self.team, subject.subject_uuid, cast(User, request.user))
        except (api.CheckConfigError, api.SubjectUnresolvableError) as error:
            raise ValidationError({"metric": str(error)})
        return Response(DataQualityOutputSchemaSerializer({"columns": columns}).data)

    @extend_schema(
        methods=["GET"],
        description="The schedule every enabled check on this subject runs on.",
        parameters=_SUBJECT_PARAMETERS,
        request=None,
        responses={200: DataQualityCheckScheduleSerializer},
    )
    @extend_schema(
        methods=["PATCH"],
        description="Change how often this subject's checks run, or stop running them automatically. "
        "Name the subject with subject_type and subject_uuid in the body.",
        request=DataQualityCheckScheduleUpdateSerializer,
        responses={200: DataQualityCheckScheduleSerializer},
    )
    @action(methods=["GET", "PATCH"], detail=False, pagination_class=None)
    def schedule(self, request: Request, **kwargs) -> Response:
        writing = request.method == "PATCH"
        subject = self._named_subject(request.data if writing else request.query_params)
        self._require_subject(subject, write=writing)
        if not api.runs_on_a_schedule(SubjectType(subject.subject_type)):
            raise ValidationError(
                {"subject_type": f"A {subject.subject_type}'s checks run when its data changes, not on a schedule."}
            )
        if not self._scheduled_checks(subject).exists():
            raise NotFound("Add a check to create this subject's schedule.")
        authorization_context = self._denial_context() if self._can_be_object_denied() else None
        if writing:
            self._require_enabled_check_access(subject)
            update = DataQualityCheckScheduleUpdateSerializer(data=request.data)
            update.is_valid(raise_exception=True)
        schedule: api.CheckSchedule | None
        try:
            if writing:
                schedule = api.update_schedule(
                    self.team_id,
                    SubjectType(subject.subject_type),
                    subject.subject_uuid,
                    user=cast(User, request.user),
                    authorization_context=authorization_context,
                    **update.schedule_changes,
                )
            else:
                schedule = api.get_schedule_with_history(
                    self.team_id, SubjectType(subject.subject_type), subject.subject_uuid, authorization_context
                )
            if schedule is None:
                raise api.ScheduleUnavailableError()
        except api.ScheduleUnavailableError as error:
            raise ScheduleUnavailableAPIError() from error
        return Response(DataQualityCheckScheduleSerializer(schedule).data)

    @extend_schema(
        description="The schedule of every subject in the project whose checks run on one, for the checks "
        "the caller may read. One request for the overview instead of one per subject.",
        request=None,
        responses={200: DataQualitySubjectScheduleSerializer(many=True)},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def schedules(self, request: Request, **kwargs) -> Response:
        scheduled_kinds = [kind for kind in SubjectType if api.runs_on_a_schedule(kind)]
        checks = self.filter_queryset(self.get_queryset()).filter(subject_type__in=scheduled_kinds)
        subjects = sorted(
            {(SubjectType(check.subject_type), check.subject_uuid) for check in checks if check.subject_uuid}
        )
        authorization_context = self._denial_context() if self._can_be_object_denied() else None
        try:
            schedules = api.list_schedules_with_history(self.team_id, subjects, authorization_context)
        except api.ScheduleUnavailableError as error:
            raise ScheduleUnavailableAPIError() from error
        return Response(DataQualitySubjectScheduleSerializer(schedules, many=True).data)

    def _scheduled_checks(self, subject: api.SubjectIdentity) -> QuerySet[DataQualityCheck]:
        return api.checks_for_subject(self.team_id, subject.subject_type, subject.subject_uuid, include_deleted=True)


@extend_schema_view(
    list=extend_schema(
        description="Every check-suite run in the project, newest first. Narrow it to one subject "
        "with subject_type and subject_uuid.",
        parameters=_SUBJECT_PARAMETERS,
    ),
)
class DataQualityRunViewSet(
    _ProjectQualityViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Check-suite executions: start one over a selection, and read every run the project has had.

    A suite run may sweep several subjects at once -- a manual project-wide run, a materialization,
    a source sync -- so it is reported here rather than under any one of them.
    """

    QUERY_GATED_ACTIONS = frozenset({"list", "retrieve", "create", "check_runs"})
    serializer_class = DataQualitySuiteRunSerializer
    queryset = DataQualitySuiteRun.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[DataQualitySuiteRun]) -> QuerySet[DataQualitySuiteRun]:
        queryset = queryset.filter(team_id=self.team_id).order_by("-created_at")
        if self.action != "list":
            return queryset
        subject = self._optional_subject(self.request.query_params)
        if subject is None:
            return queryset
        self._require_subject(subject, write=False)
        return queryset.filter(subject_type=subject.subject_type, subject_uuid=subject.subject_uuid)

    def filter_queryset(self, queryset: QuerySet[DataQualitySuiteRun]) -> QuerySet[DataQualitySuiteRun]:
        """Withhold the suites that report on a subject the caller is denied.

        A suite row carries its subject and its passed/failed/errored/skipped counters, so serving
        one is serving outcome counts over the rows behind it. Excluded in SQL rather than filtered
        per page, so the paginated count cannot report the withheld suites either.

        ``check_runs`` is left alone on purpose: it already drops the individual runs that read a
        denied subject, and hiding the suite there would take the readable runs down with them.
        """
        queryset = super().filter_queryset(queryset)
        if self.action == "check_runs":
            return queryset
        if not self._can_be_object_denied():
            return queryset
        # A suite with runs is withheld when any of them touched a subject out of reach, the same
        # rule the check routes apply. A suite that swept nothing has no run to gate on, so its own
        # subject gates it directly -- which is the only path that reaches an empty suite.
        context = self._denial_context()
        return queryset.exclude(api.unreadable_suites_q(context)).exclude(
            api.suites_backing_unreadable_runs_q(self.team_id, context)
        )

    @extend_schema(
        description="Every check execution in this suite run.",
        responses={200: DataQualityCheckRunSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True, url_path="check_runs", pagination_class=None)
    def check_runs(self, request: Request, **kwargs) -> Response:
        suite_run = self.get_object()
        runs = list(
            self._readable_runs(DataQualityCheckRun.objects.for_team(self.team_id).filter(suite_run=suite_run))
            .select_related("quality_check")
            .order_by("-created_at")
        )
        serializer = DataQualityCheckRunSerializer(
            runs, many=True, context={"unnamable_check_ids": self._unnamable_check_ids(runs)}
        )
        return Response(serializer.data)

    @extend_schema(
        description="Run checks now: the ones named by check_ids, every enabled check on the subject named by "
        "subject_type and subject_uuid, or every enabled check in the project when neither is given. "
        "Returns the suite run to poll for the report.",
        request=DataQualityRunRequestSerializer,
        responses={200: DataQualitySuiteRunSerializer},
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = DataQualityRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested = [str(check_id) for check_id in serializer.validated_data.get("check_ids") or []]
        subject = self._optional_subject(serializer.validated_data)
        if subject is not None and not requested:
            return Response(self._run_subject(subject, cast(User, request.user)))

        runnable = api.live_subject_checks(
            DataQualityCheck.objects.for_team(self.team_id).filter(deleted=False, enabled=True)
        )
        if requested:
            runnable = runnable.filter(id__in=requested)
        elif self._can_be_object_denied():
            runnable = api.readable_check_subjects(runnable, self._writable_subjects)
        checks = self._authorized_checks(list(runnable), named=bool(requested))
        if not checks:
            # An empty selection cannot be handed to the worker: it reads as no selector at all and
            # would sweep the project, which is the opposite of what the caller may run.
            suite_run = api.empty_check_suite(team=self.team, user=cast(User, request.user))
        else:
            suite_run = api.start_check_suite(
                team=self.team,
                user=cast(User, request.user),
                check_ids=[str(check.id) for check in checks],
            )
        return Response(DataQualitySuiteRunSerializer(suite_run).data)

    def _run_subject(self, subject: api.SubjectIdentity, user: User) -> dict:
        """Run every enabled check on one subject, stamping the suite with it so it reads back scoped.

        Pointing at a subject is naming what to run, so a check on it the caller may not reach is a
        403 rather than something quietly dropped.
        """
        self._require_subject(subject, write=True)
        self._require_enabled_check_access(subject)
        suite_run = api.start_check_suite(
            team=self.team,
            user=user,
            subject_type=subject.subject_type,
            subject_uuids=[subject.subject_uuid],
        )
        return DataQualitySuiteRunSerializer(suite_run).data

    def _authorized_checks(self, checks: list[DataQualityCheck], named: bool) -> list[DataQualityCheck]:
        """Drop, or reject, the checks this member may not run.

        Naming a denied check is an attempt to read it, so it 403s the way the per-subject run does.
        Sweeping the project is not: a denied subject is one the member cannot see at all, so its
        checks are simply not part of "everything" for them.

        This route is the one that actually executes a query against the subject, so it reads the
        name from the subject itself like the listing routes do. Matching the copy stamped on the
        check would let a table renamed since its last run be run against, and its pass/fail and
        row counts read back.
        """
        allowed_types = self._authorized_subject_types(write=True)
        if named and any(check.subject_type not in allowed_types for check in checks):
            raise PermissionDenied("You don't have permission to run a check on this subject.")
        checks = [check for check in checks if check.subject_type in allowed_types]
        if not self._can_be_object_denied():
            return checks
        readable = self._writable_subjects
        self._metric_subjects.update(
            api.resolve_metric_subjects(
                self.team_id,
                {
                    check.metric_id
                    for check in checks
                    if check.metric_id is not None and readable.contains(check.subject_type, check.subject_uuid)
                },
            )
        )
        allowed = []
        for check in checks:
            if not readable.contains(check.subject_type, check.subject_uuid):
                if named:
                    raise PermissionDenied("You don't have access to a table or view this check reads.")
                continue
            try:
                self._require_referenced_subject_access(
                    check.check_type,
                    check.config,
                    subject=self._check_identity(check),
                )
            except PermissionDenied:
                if named:
                    raise
                continue
            allowed.append(check)
        return allowed


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
