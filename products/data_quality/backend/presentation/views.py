"""DRF views for data quality checks, nested under the subjects they audit.

Checks hang off the existing warehouse surfaces -- ``warehouse_saved_queries/{id}/checks`` and
``warehouse_tables/{id}/checks`` -- the same way run/materialize/resume do, gated by warehouse
scopes rather than a scope of their own. Thin: validate via the serializer, call the facade,
serialize the result. Nothing here runs a check -- every trigger hands off to Temporal and returns
a suite-run handle to poll.
"""

import json
from collections import defaultdict
from collections.abc import Callable
from typing import ClassVar, cast
from uuid import UUID

from django.db.models import QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin

from ..facade import api
from ..facade.enums import CheckRunStatus, SubjectStatus, SubjectType
from ..facade.flags import is_data_quality_checks_enabled
from ..facade.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from .serializers import (
    CheckTypeSerializer,
    DataQualityCheckRunSerializer,
    DataQualityCheckSerializer,
    DataQualityGateConfigSerializer,
    DataQualityOverviewCheckSerializer,
    DataQualityRunRequestSerializer,
    DataQualitySuiteRunSerializer,
    SubjectHealthSerializer,
)

_RECENT_RUNS_LIMIT = 50


def _current_subject_name(check: DataQualityCheck, current_names: dict[api.SubjectIdentity, str]) -> str:
    # A hard-deleted subject nulls the FK, leaving nothing to resolve and only the name the last run
    # stamped on the check.
    if check.subject_uuid is None:
        return check.subject_name
    return current_names.get(api.subject_identity(check.subject_type, check.subject_uuid), check.subject_name)


class _QualityGatedViewSet(TeamAndOrgViewSetMixin):
    """The gating every data quality surface shares, whether or not it is nested under a subject.

    Entry points are gated on the product flag, and most additionally on query access: run results
    are a count oracle over the underlying rows, so a member denied `query` must not reach them
    through a check. Only the check-type *catalog* stays ungated by query: static schema metadata.

    Denial is name-based, reading the same set the information_schema loaders do, so REST and SQL
    can never disagree about which subjects a member may see.
    """

    team: Team
    QUERY_GATED_ACTIONS: ClassVar[frozenset[str]] = frozenset()

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

    def _can_be_object_denied(self) -> bool:
        # Shared with the information_schema loaders, so the two surfaces agree on which callers a
        # gate applies to as well as on what it decides.
        return api.can_be_object_denied(self.user_access_control)

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

    def _reads_unreadable_subject(self, check_type: str, config: dict) -> bool:
        """Whether this definition reads a subject the caller cannot be shown to be allowed.

        The parent is not the only subject a check reads: a relationships check names a second
        subject and a custom_sql query selects arbitrary tables, both run by the worker with team
        scope only. Authorize them too, or a check on an allowed subject is a count oracle over a
        denied one.

        A denied name is only the case where the subject still exists. Deleting it takes its denial
        with it, so a name that neither resolves nor is denied proves nothing either way and is
        refused on the same fail-closed terms.
        """
        # A type that cannot read past its own subject has nothing here to authorize. The verdict on
        # one that can is a pure function of its definition, so a project-wide page parses and
        # resolves each distinct definition once rather than once per check carrying it.
        if not api.check_type_reads_beyond_subject(check_type):
            return False
        cache: dict[str, bool] = getattr(self, "_reads_unreadable_cache", {})
        self._reads_unreadable_cache = cache
        key = json.dumps([check_type, config], sort_keys=True, default=str)
        if key not in cache:
            cache[key] = self._definition_reads_unreadable_subject(check_type, config)
        return cache[key]

    def _definition_reads_unreadable_subject(self, check_type: str, config: dict) -> bool:
        refs = api.referenced_subjects(self.team.id, check_type, config)
        if refs.unresolved_reference:
            return True
        if any(api.is_subject_denied(name, self._denied_subject_names()) for name in refs.names):
            return True
        return bool(self._unconfirmable_names(refs.names))

    def _unconfirmable_names(self, names: tuple[str, ...]) -> set[str]:
        # Memoized per request: the lookup rebuilds the caller's HogQL database, and a suite re-runs
        # the same definitions.
        cache: dict[str, bool] = getattr(self, "_unconfirmable_cache", {})
        self._unconfirmable_cache = cache
        unseen = tuple(name for name in names if name not in cache)
        if unseen:
            unconfirmable = api.unconfirmable_subject_names(
                self.team,
                cast(User, self.request.user),
                unseen,
                user_access_control=self.user_access_control,
            )
            cache.update({name: name in unconfirmable for name in unseen})
        return {name for name in names if cache[name]}

    def _require_referenced_subject_access(self, check_type: str, config: dict) -> None:
        if not self._can_be_object_denied():
            return
        if self._reads_unreadable_subject(check_type, config):
            raise PermissionDenied("You don't have access to a table or view this check reads.")

    def _denied_checks(self, checks: list[DataQualityCheck], denied: set[str]) -> set[UUID]:
        """The ids of the checks this caller may not see, over a page of them.

        A check is out of reach on any of three counts: its own subject is denied, the definition it
        would run next reads one that is, or the run behind its ``last_status`` read one. The row is
        both tenses at once -- a definition and the verdict of a past run -- so each is judged by the
        rule for its own tense, the definition by the names it resolves today and the run by the
        identities it pinned.

        Subject names come from the subjects themselves rather than from the copy denormalized onto
        the check, which only a run rewrites, so a rename cannot carry a denied subject back into a
        list.
        """
        recordings = api.latest_run_recordings(self.team_id, [check.id for check in checks])
        subjects = [
            api.subject_identity(check.subject_type, check.subject_uuid) for check in checks if check.subject_uuid
        ]
        subjects += api.pinned_subject_refs(recording.referenced_subjects for recording in recordings.values())
        current_names = api.resolve_subject_names(self.team_id, subjects)
        return {
            check.id
            for check in checks
            if api.is_subject_denied(_current_subject_name(check, current_names), denied)
            or self._reads_unreadable_subject(check.check_type, check.config)
            or self._last_run_read_an_unreadable_subject(recordings.get(check.id), current_names, denied)
        }

    def _last_run_read_an_unreadable_subject(
        self, recording: api.RunRecording | None, current_names: dict[api.SubjectIdentity, str], denied: set[str]
    ) -> bool:
        # A check that never ran carries no verdict, so there is nothing here to authorize.
        if recording is None:
            return False
        return api.run_reads_unreadable_subject(
            recording.check_type, recording.referenced_subjects, current_names, denied
        )

    def _readable_runs(self, runs: list[DataQualityCheckRun]) -> list[DataQualityCheckRun]:
        """Drop the runs that read a subject the caller cannot be shown to be allowed.

        Every identity in the page resolves in one pass rather than one query per run, since a
        suite re-runs the same checks over the same subjects.
        """
        if not self._can_be_object_denied():
            return runs
        current_names = api.resolve_subject_names(
            self.team_id, api.pinned_subject_refs(run.referenced_subjects for run in runs)
        )
        denied = self._denied_subject_names()
        return [
            run
            for run in runs
            if not api.run_reads_unreadable_subject(run.check_type, run.referenced_subjects, current_names, denied)
        ]


class _SubjectScopedViewSet(_QualityGatedViewSet):
    """Adds the parent-subject gate for viewsets nested under a warehouse saved query or table."""

    subject_type: ClassVar[SubjectType]
    subject_field: ClassVar[str]

    @property
    def subject_uuid(self) -> str:
        return str(self.parents_query_dict[f"{self.subject_field}_id"])

    def initial(self, request: Request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        self._require_parent_subject_access()

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


_EDIT_DESCRIPTION = (
    "Edit this check in place, including what it asserts (check_type, column_name, config). The "
    "table or view it audits is fixed, and the check keeps its id, run history, latest status, and "
    "latest run time. A definition or name already held by another active check comes back as a "
    "field error, with nothing written."
)


@extend_schema_view(
    update=extend_schema(description=_EDIT_DESCRIPTION),
    partial_update=extend_schema(description=_EDIT_DESCRIPTION),
)
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

    def filter_queryset(self, queryset: QuerySet[DataQualityCheck]) -> QuerySet[DataQualityCheck]:
        # The parent gate cleared this subject, but a check under it can read a second one. Its
        # config names that subject, and its status answers questions about the rows behind it.
        queryset = super().filter_queryset(queryset)
        # Listing only. The routes that address one check keep answering 403 with what is wrong,
        # which tells the caller more than the 404 that hiding the row would give them.
        if self.action != "list":
            return queryset
        if not self._can_be_object_denied():
            return queryset
        return queryset.exclude(id__in=self._denied_checks(list(queryset), self._denied_subject_names()))

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

    def perform_update(self, serializer: BaseSerializer) -> None:
        # The candidate definition, not the stored one: an edit that points the check at a new
        # relationships target or rewrites its custom SQL has to clear that subject too, before it
        # is saved and the worker starts running it.
        check = cast(DataQualityCheck, serializer.instance)
        data = serializer.validated_data
        self._require_referenced_subject_access(
            data.get("check_type", check.check_type), data.get("config", check.config) or {}
        )
        serializer.save()

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
        if self._can_be_object_denied():
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
        # The current definition gates the check itself; each run is then judged on the definition
        # it executed, so editing a check into a harmless one does not unlock what it used to read.
        self._require_referenced_subject_access(check.check_type, check.config)
        runs = list(
            DataQualityCheckRun.objects.for_team(self.team_id)
            .filter(quality_check=check)
            .select_related("quality_check")
            .order_by("-created_at")[:_RECENT_RUNS_LIMIT]
        )
        return Response(DataQualityCheckRunSerializer(self._readable_runs(runs), many=True).data)

    @extend_schema(
        description="Health rollup for this table or view, from the denormalized status of its checks.",
        responses={200: SubjectHealthSerializer},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def health(self, request: Request, **kwargs) -> Response:
        # A rollup counts the checks it covers, so it has to cover the same ones the list serves.
        # Rolled up from the rows that survive rather than through subject_health(), which would go
        # back to the database and count the withheld ones straight back in.
        checks = list(api.checks_for_subject(self.team_id, self.subject_type, self.subject_uuid).filter(enabled=True))
        if self._can_be_object_denied():
            withheld = self._denied_checks(checks, self._denied_subject_names())
            checks = [check for check in checks if check.id not in withheld]
        return Response(
            SubjectHealthSerializer(
                {
                    "subject_type": self.subject_type,
                    "subject_uuid": self.subject_uuid,
                    "health": api.roll_up_health(
                        api.CheckStatusRow(severity=check.severity, last_status=check.last_status) for check in checks
                    ),
                    "checks_total": len(checks),
                    "checks_failing": sum(1 for check in checks if check.last_status == CheckRunStatus.FAILED),
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

    def filter_queryset(self, queryset: QuerySet[DataQualitySuiteRun]) -> QuerySet[DataQualitySuiteRun]:
        """Withhold the suites whose executions read a subject the caller is denied.

        The parent gate clears the declared subject, but a suite row carries passed/failed/errored/
        skipped over every check it ran, while ``check_runs`` hands back only the readable ones.
        Serving both names the withheld check's outcome by subtraction.
        """
        queryset = super().filter_queryset(queryset)
        # check_runs is left alone on purpose: it already drops the individual runs that read a
        # denied subject, and hiding the suite there would take the readable runs down with them.
        if self.action not in ("list", "retrieve"):
            return queryset
        if not self._can_be_object_denied():
            return queryset
        # Only the runs behind the suites this parent serves, so answering for one subject does not
        # walk the project's whole history.
        runs = DataQualityCheckRun.objects.for_team(self.team_id).filter(
            suite_run_id__in=queryset.order_by().values("id")
        )
        unreadable = api.unreadable_runs_q(self.team_id, self._denied_subject_names())
        return queryset.exclude(id__in=runs.filter(unreadable).values("suite_run_id"))

    @extend_schema(
        description="Every check execution in this suite run.",
        responses={200: DataQualityCheckRunSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True, url_path="check_runs", pagination_class=None)
    def check_runs(self, request: Request, **kwargs) -> Response:
        suite_run = self.get_object()
        runs = list(
            DataQualityCheckRun.objects.for_team(self.team_id)
            .filter(suite_run=suite_run)
            .select_related("quality_check")
            .order_by("-created_at")
        )
        return Response(DataQualityCheckRunSerializer(self._readable_runs(runs), many=True).data)


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


class DataQualityCheckOverviewViewSet(
    _QualityGatedViewSet,
    AccessControlViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Every check in the project, and the health of every subject that has one.

    The per-subject surfaces answer "what is wrong with this table". This answers "what is wrong
    across the project", which they cannot: each is nested under one parent. Read-only -- authoring
    still happens against the subject that owns the check.
    """

    QUERY_GATED_ACTIONS = frozenset({"list", "health"})
    scope_object = "warehouse_objects"
    serializer_class = DataQualityOverviewCheckSerializer
    queryset = DataQualityCheck.objects.unscoped()
    _subject_locations: dict[api.SubjectKey, api.SubjectLocation] = {}

    def safely_get_queryset(self, queryset: QuerySet[DataQualityCheck]) -> QuerySet[DataQualityCheck]:
        # Orphans are excluded: their subject is gone, so there is no page to link to, nothing to
        # run, and no rollup to sit under. The run history they left behind stays queryable.
        return (
            queryset.filter(team_id=self.team_id, deleted=False)
            .exclude(subject_status=SubjectStatus.ORPHANED)
            .order_by("subject_name", "name")
        )

    def get_serializer_context(self) -> dict:
        return {**super().get_serializer_context(), "subject_locations": self._subject_locations}

    def list(self, request: Request, *args, **kwargs) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        checks = list(queryset) if page is None else page
        # Resolved once for the page, so linking to a subject costs two queries rather than one per
        # check. Anything the batch cannot resolve stays absent and renders as plain text.
        self._subject_locations = api.subject_locations(self.team_id, checks)
        serializer = self.get_serializer(checks, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    def filter_queryset(self, queryset: QuerySet[DataQualityCheck]) -> QuerySet[DataQualityCheck]:
        # Hiding a denied subject's checks matters more here than on the nested surfaces: this one
        # lists everything, so a leak is a directory of the tables a member cannot read. Denial is
        # matched by name rather than equality, so the pass has to happen in Python; only a
        # restricted member pays for it, since the denied set is empty for everyone else.
        queryset = super().filter_queryset(queryset)
        if not self._can_be_object_denied():
            return queryset
        return queryset.exclude(id__in=self._denied_checks(list(queryset), self._denied_subject_names()))

    @extend_schema(
        description="Health rollup for every table and view in the project that has checks.",
        responses={200: SubjectHealthSerializer(many=True)},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def health(self, request: Request, **kwargs) -> Response:
        # Rolled up from the checks already loaded, using the same rule as the per-subject endpoint.
        # Calling subject_health() per subject would be a query per table.
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


class DataQualityRunViewSet(
    _QualityGatedViewSet,
    AccessControlViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Project-wide check runs: start one over a selection, and read every run the project has had.

    The per-subject surfaces only serve runs scoped to their own subject, so this is where a sweep
    across several subjects -- a manual project-wide run, a materialization, a source sync -- is
    readable. Scoped to `warehouse_objects` because it spans tables and views at once.
    """

    QUERY_GATED_ACTIONS = frozenset({"list", "retrieve", "create"})
    scope_object = "warehouse_objects"
    serializer_class = DataQualitySuiteRunSerializer
    queryset = DataQualitySuiteRun.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[DataQualitySuiteRun]) -> QuerySet[DataQualitySuiteRun]:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    def filter_queryset(self, queryset: QuerySet[DataQualitySuiteRun]) -> QuerySet[DataQualitySuiteRun]:
        """Withhold the suites that report on a subject the caller is denied.

        A suite row carries its subject and its passed/failed/errored/skipped counters, so serving
        one is serving outcome counts over the rows behind it. The nested suite lists are gated by
        their parent; this one spans every subject and has no parent to gate on. Excluded in SQL
        rather than filtered per page, so the paginated count cannot report the withheld suites
        either.
        """
        queryset = super().filter_queryset(queryset)
        if not self._can_be_object_denied():
            return queryset
        # A suite with runs is withheld when any of them touched a denied subject, the same rule the
        # check routes apply. A suite that swept nothing has no run to gate on, so its own subject
        # gates it directly -- which is the only path that reaches an empty suite.
        denied_uuids = self._denied_subject_uuids()
        if denied_uuids:
            queryset = queryset.exclude(subject_uuid__in=denied_uuids)
        unreadable = api.unreadable_runs_q(self.team_id, self._denied_subject_names())
        runs = DataQualityCheckRun.objects.for_team(self.team_id).filter(unreadable)
        return queryset.exclude(id__in=runs.values("suite_run_id"))

    def _denied_subject_uuids(self) -> set[UUID]:
        """The ids of the subjects a suite in this project targets that the caller is denied.

        Resolved from the subjects themselves rather than a name a suite denormalized, so a subject
        renamed since still matches its own denial. A suite records only its subject's id, not a
        name, so one that no longer resolves cannot be judged by the name it ran under here.
        """
        denied = self._denied_subject_names()
        identities = {
            api.subject_identity(subject_type, subject_uuid)
            for subject_type, subject_uuid in DataQualitySuiteRun.objects.for_team(self.team_id)
            .values_list("subject_type", "subject_uuid")
            .distinct()
            if subject_uuid is not None
        }
        current_names = api.resolve_subject_names(self.team_id, identities)
        return {
            UUID(identity.subject_uuid)
            for identity in identities
            if (name := current_names.get(identity)) is not None and api.is_subject_denied(name, denied)
        }

    @extend_schema(
        description="Run the named checks now, or every enabled check in the project when none are named. "
        "Returns the suite run to poll for the report.",
        request=DataQualityRunRequestSerializer,
        responses={200: DataQualitySuiteRunSerializer},
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = DataQualityRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested = [str(check_id) for check_id in serializer.validated_data.get("check_ids") or []]

        runnable = DataQualityCheck.objects.for_team(self.team_id).filter(deleted=False, enabled=True)
        if requested:
            runnable = runnable.filter(id__in=requested)
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
        if not self._can_be_object_denied():
            return checks
        denied = self._denied_subject_names()
        current_names = api.resolve_subject_names(
            self.team_id,
            [api.subject_identity(check.subject_type, check.subject_uuid) for check in checks if check.subject_uuid],
        )
        allowed = []
        for check in checks:
            if api.is_subject_denied(_current_subject_name(check, current_names), denied):
                if named:
                    raise PermissionDenied("You don't have access to a table or view this check reads.")
                continue
            self._require_referenced_subject_access(check.check_type, check.config)
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
