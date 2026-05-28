"""
DRF viewsets for agent_stack — the authoring surface.

Two model viewsets + one catalog viewset:

    AgentApplicationViewSet  list / retrieve / create / update / destroy /
                             set_env
    AgentRevisionViewSet     list / retrieve / create (draft) / update_spec /
                             promote / archive  +  bundle proxy actions
                             (manifest, file, bundle, freeze, clone_from)
    AgentNativeToolsViewSet  list (read-only catalog of native tools)

Bundle reads/writes are proxied to the agent-janitor node service which
owns the actual BundleStore (FS in dev, S3 in prod). The Django layer keeps
its team / scope / draft-only checks and forwards the body. See
janitor_client.py for the wire protocol.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer
from rest_framework import (
    serializers as drf_serializers,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.encrypted_fields import EncryptedTextField

from .janitor_client import JanitorClient, JanitorClientError, default_client
from .models import AgentApplication, AgentRevision
from .serializers import (
    AgentApplicationSerializer,
    AgentRevisionSerializer,
    CloneFromRequestSerializer,
    NewDraftRevisionRequestSerializer,
    PromoteRevisionRequestSerializer,
    SetEnvRequestSerializer,
    WriteBundleRequestSerializer,
    WriteFileRequestSerializer,
)

logger = logging.getLogger(__name__)


def _resolve_application(queryset: QuerySet, lookup_value: str) -> AgentApplication | None:
    """Look up by UUID if the URL value parses as one, otherwise by slug.

    Lets API consumers reference an application either by its stable id or by
    the human-readable slug — both are unique within a team.
    """
    try:
        UUID(str(lookup_value))
        field = "pk"
    except (ValueError, TypeError):
        field = "slug"
    return queryset.filter(**{field: lookup_value}).first()


def _janitor() -> JanitorClient:
    """Indirection so tests can monkey-patch."""
    return default_client()


class JanitorUpstreamError(APIException):
    """DRF-friendly wrapper for non-2xx janitor responses. We forward the
    status code where it makes sense (404 stays 404, 409 stays 409) and
    surface the janitor's body as the API response."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Upstream janitor service error"
    default_code = "janitor_upstream"

    def __init__(self, e: JanitorClientError) -> None:
        # Preserve 4xx mappings; clamp 5xx to a single 502 so we never leak
        # the janitor's internal status (some are nominal like 503 = not
        # configured, but the caller experience is "this isn't available").
        upstream_code = e.status_code
        if 400 <= upstream_code < 500:
            self.status_code = upstream_code
        detail = e.body if e.body is not None else {"detail": e.message}
        super().__init__(detail=detail)


@extend_schema(tags=["agent_stack"])
class AgentApplicationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Agent applications — the deployable unit of the platform.

    URLs:
        GET    /api/projects/<team>/agent_applications/             list
        POST   /api/projects/<team>/agent_applications/             create
        GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
        PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
        DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
        POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
    """

    scope_object = "agent_application"
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "set_env"]
    scope_object_read_actions = ["list", "retrieve", "sessions_list", "sessions_retrieve"]
    serializer_class = AgentApplicationSerializer
    queryset = AgentApplication.objects.all()

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(archived=False)

    def safely_get_object(self, queryset: QuerySet) -> AgentApplication | None:
        return _resolve_application(queryset, self.kwargs[self.lookup_url_kwarg or self.lookup_field])

    def perform_create(self, serializer: AgentApplicationSerializer) -> None:
        serializer.save(team_id=self.team_id, created_by=self.request.user)

    def perform_destroy(self, instance: AgentApplication) -> None:
        """Soft-delete: archived=True, archived_at=NOW. Preserves audit history."""
        instance.archived = True
        instance.archived_at = timezone.now()
        instance.save(update_fields=["archived", "archived_at", "updated_at"])

    @extend_schema(request=SetEnvRequestSerializer)
    @action(detail=True, methods=["post"], url_path="set_env")
    def set_env(self, request: Request, **kwargs) -> Response:
        """Replace the agent's encrypted env block.

        The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
        text gets stored on AgentApplication.encrypted_env; the worker
        decrypts it at session start via the same Fernet schedule (see
        agent-shared/src/runtime/encryption.ts).
        """
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")

        body = SetEnvRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        env_map = body.validated_data["env"]

        # EncryptedTextField encrypts on assignment when saved.
        # We serialize the env dict as JSON before encryption so the worker
        # gets a JSON object back out.
        application.encrypted_env = json.dumps(env_map)
        application.save(update_fields=["encrypted_env", "updated_at"])
        return Response({"ok": True})

    @extend_schema(
        operation_id="agent_applications_sessions_list",
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentApplicationSessionsListResponse",
                fields={
                    "sessions": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentSessionSummary",
                            fields={
                                "id": drf_serializers.UUIDField(),
                                "application_id": drf_serializers.UUIDField(),
                                "revision_id": drf_serializers.UUIDField(),
                                "state": drf_serializers.CharField(),
                                "external_key": drf_serializers.CharField(allow_null=True),
                                "principal": drf_serializers.DictField(allow_null=True),
                                "turns": drf_serializers.IntegerField(),
                                "retry_count": drf_serializers.IntegerField(),
                                "created_at": drf_serializers.DateTimeField(),
                                "updated_at": drf_serializers.DateTimeField(),
                            },
                        ),
                    ),
                },
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="sessions")
    def sessions_list(self, request: Request, **kwargs) -> Response:
        """List sessions for this application, newest first. Strips the
        conversation transcript from each summary — fetch a single session
        via /sessions/<id>/ for the full body."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        limit_param = request.query_params.get("limit")
        offset_param = request.query_params.get("offset")
        try:
            limit = int(limit_param) if limit_param is not None else None
            offset = int(offset_param) if offset_param is not None else None
        except ValueError:
            raise ValidationError("limit and offset must be integers")
        try:
            payload = _janitor().list_sessions(str(application.id), limit=limit, offset=offset)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_applications_sessions_retrieve",
        parameters=[
            OpenApiParameter(
                "session_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                required=True,
                description="UUID of the session to fetch (must belong to this application).",
            ),
        ],
        request=None,
    )
    @action(detail=True, methods=["get"], url_path="sessions/(?P<session_id>[^/.]+)")
    def sessions_retrieve(self, request: Request, session_id: str = "", **kwargs) -> Response:
        """Fetch one session's full state, including the conversation transcript.
        The runner-side queue DB is the source of truth for this — the response
        shape mirrors `AgentSession`."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        try:
            payload = _janitor().get_session(session_id)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        # Cross-check ownership: the janitor doesn't know about teams. Reject
        # if the session belongs to a different application than the URL says.
        if payload.get("application_id") != str(application.id):
            raise NotFound("Session not found")
        return Response(payload)


@extend_schema(tags=["agent_stack"])
class AgentRevisionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Revisions of an agent. Created in `draft`, promoted through
    `ready → live` once the bundle has been uploaded + frozen.

    URLs (nested under an application):

        Model CRUD:
            GET   .../revisions/                       list
            POST  .../revisions/                       create draft
            GET   .../revisions/<id>/                  retrieve
            PATCH .../revisions/<id>/                  update spec (draft only)

        Lifecycle:
            POST  .../revisions/<id>/promote/          ready → live
            POST  .../revisions/<id>/archive/          → archived
            POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
            POST  .../revisions/<id>/clone_from/       copy bundle from another rev
            POST  .../revisions/new_draft/             create draft + clone_from atomically

        Bundle authoring (proxied to the janitor):
            GET    .../revisions/<id>/manifest/        list paths + sha256
            GET    .../revisions/<id>/file/?path=…     read one file
            PUT    .../revisions/<id>/file/?path=…     write one file (draft)
            DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
            GET    .../revisions/<id>/bundle/          bulk pull all files
            PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
    """

    scope_object = "agent_application"  # share the parent's scope
    # AgentRevision is tenant-scoped via its parent application, not directly.
    # The URL kwarg `project_id` from the parent router defaults to filtering
    # `team__project_id` on the queryset, but AgentRevision only has
    # `application__team__project_id`. Rewrite the parent lookup accordingly.
    filter_rewrite_rules = {"project_id": "application__team__project_id"}
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "promote",
        "archive",
        "freeze",
        "clone_from",
        "new_draft",
        "put_file",
        "delete_file",
        "put_bundle",
    ]
    scope_object_read_actions = ["list", "retrieve", "manifest", "get_file", "get_bundle", "validate"]
    serializer_class = AgentRevisionSerializer
    queryset = AgentRevision.objects.all()

    def get_application(self) -> AgentApplication:
        # drf-extensions nested routing passes the parent URL kwarg as
        # `parent_lookup_application_id` (see `parents_query_lookups` in the
        # nested router registration in posthog/api/__init__.py).
        app = _resolve_application(
            AgentApplication.objects.filter(team_id=self.team_id, archived=False),
            self.kwargs.get("parent_lookup_application_id") or self.kwargs.get("application_id"),
        )
        if app is None:
            raise NotFound("Application not found")
        return app

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(application=self.get_application())

    def perform_create(self, serializer: AgentRevisionSerializer) -> None:
        application = self.get_application()
        # Fresh revisions start in `draft`. Parent revision is optional — if
        # set, this revision can later be diff'd against it for review.
        serializer.save(
            application=application,
            state="draft",
            created_by=self.request.user,
        )

    def update(self, request: Request, *args, **kwargs) -> Response:
        """Spec edits are only allowed while state='draft'. Once promoted to
        ready/live the spec is frozen — change requires a new revision."""
        instance: AgentRevision = self.get_object()
        if instance.state != "draft":
            raise ValidationError(f"Cannot edit spec on a {instance.state} revision; create a new draft instead.")
        return super().update(request, *args, **kwargs)

    @extend_schema(request=PromoteRevisionRequestSerializer)
    @action(detail=True, methods=["post"], url_path="promote")
    def promote(self, request: Request, **kwargs) -> Response:
        """ready → live. Sets the parent application's live_revision."""
        revision: AgentRevision = self.get_object()
        body = PromoteRevisionRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        if revision.state == "live":
            return Response({"ok": True, "state": "live", "no_op": True})
        if revision.state != "ready":
            raise ValidationError(f"Revision is in state '{revision.state}'; only 'ready' can be promoted.")
        if not revision.bundle_sha256:
            raise ValidationError("Revision has no frozen bundle (bundle_sha256 is null).")

        application = revision.application
        # Demote whatever's currently live, if anything different.
        previously_live = application.live_revision
        if previously_live and previously_live.id != revision.id:
            previously_live.state = "archived"
            previously_live.save(update_fields=["state", "updated_at"])

        revision.state = "live"
        revision.save(update_fields=["state", "updated_at"])
        application.live_revision = revision
        application.save(update_fields=["live_revision", "updated_at"])
        return Response({"ok": True, "state": "live"})

    @extend_schema(request=None)
    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request: Request, **kwargs) -> Response:
        """Mark a revision archived. If it was the live one, clear the
        application's live_revision pointer (the app effectively has no
        deployable version until another revision is promoted)."""
        revision: AgentRevision = self.get_object()
        if revision.state == "archived":
            return Response({"ok": True, "no_op": True})
        application = revision.application
        revision.state = "archived"
        revision.save(update_fields=["state", "updated_at"])
        if application.live_revision_id == revision.id:
            application.live_revision = None
            application.save(update_fields=["live_revision", "updated_at"])
        return Response({"ok": True, "state": "archived"})

    # ── Bundle proxy actions ───────────────────────────────────────────────

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Wrap a janitor call: map upstream errors into DRF responses."""
        try:
            return fn(*args, **kwargs)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e

    @extend_schema(request=None)
    @action(detail=True, methods=["get"], url_path="manifest")
    def manifest(self, request: Request, **kwargs) -> Response:
        """List every file in this revision's bundle (path, size, sha256)."""
        revision: AgentRevision = self.get_object()
        return Response(self._call(_janitor().manifest, str(revision.id)))

    # DRF routes /file/ and /bundle/ across multiple HTTP verbs via a single
    # @action + .mapping.<verb> chain. Three separate @action decorators with
    # the same url_path don't merge — the last one registered wins and the
    # others 405.
    _FILE_PATH_PARAM = OpenApiParameter(
        "path",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        required=True,
        description="Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.",
    )

    @extend_schema(parameters=[_FILE_PATH_PARAM], request=None)
    @action(detail=True, methods=["get"], url_path="file")
    def get_file(self, request: Request, **kwargs) -> Response:
        """Read one file by `?path=...`. Works on any revision state."""
        revision: AgentRevision = self.get_object()
        path = request.query_params.get("path")
        if not path:
            raise ValidationError("Missing ?path=… query parameter.")
        return Response(self._call(_janitor().get_file, str(revision.id), path))

    @extend_schema(parameters=[_FILE_PATH_PARAM], request=WriteFileRequestSerializer)
    @get_file.mapping.put
    def put_file(self, request: Request, **kwargs) -> Response:
        """Write one file by `?path=...`. Draft-only (janitor enforces)."""
        revision: AgentRevision = self.get_object()
        path = request.query_params.get("path")
        if not path:
            raise ValidationError("Missing ?path=… query parameter.")
        body = WriteFileRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(self._call(_janitor().put_file, str(revision.id), path, body.validated_data["content"]))

    @extend_schema(parameters=[_FILE_PATH_PARAM], request=None)
    @get_file.mapping.delete
    def delete_file(self, request: Request, **kwargs) -> Response:
        """Delete one file by `?path=...`. Draft-only."""
        revision: AgentRevision = self.get_object()
        path = request.query_params.get("path")
        if not path:
            raise ValidationError("Missing ?path=… query parameter.")
        return Response(self._call(_janitor().delete_file, str(revision.id), path))

    @extend_schema(request=None)
    @action(detail=True, methods=["get"], url_path="bundle")
    def get_bundle(self, request: Request, **kwargs) -> Response:
        """Bulk-pull: returns `{ files: { path: content, ... }, ... }`. Use
        this when the MCP wants the whole bundle to work on locally."""
        revision: AgentRevision = self.get_object()
        return Response(self._call(_janitor().get_bundle, str(revision.id)))

    @extend_schema(request=WriteBundleRequestSerializer)
    @get_bundle.mapping.put
    def put_bundle(self, request: Request, **kwargs) -> Response:
        """Bulk-push the bundle. Body `{ files, mode: replace|merge }`."""
        revision: AgentRevision = self.get_object()
        body = WriteBundleRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(
            self._call(
                _janitor().put_bundle,
                str(revision.id),
                body.validated_data["files"],
                body.validated_data["mode"],
            )
        )

    @extend_schema(
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentRevisionValidateResponse",
                fields={
                    "ok": drf_serializers.BooleanField(),
                    "revision_id": drf_serializers.UUIDField(),
                    "revision_state": drf_serializers.CharField(),
                    "errors": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentRevisionValidationError",
                            fields={
                                "code": drf_serializers.CharField(),
                                "message": drf_serializers.CharField(),
                                "pointer": drf_serializers.CharField(),
                            },
                        ),
                    ),
                    "resolved_natives": drf_serializers.ListField(child=drf_serializers.CharField()),
                },
            )
        ),
    )
    @action(detail=True, methods=["post"], url_path="validate")
    def validate(self, request: Request, **kwargs) -> Response:
        """Pre-flight checks before freeze + promote: entrypoint file exists,
        every native tool id is registered, every custom tool has its
        compiled.js + schema.json, every skill path exists, every declared
        secret has a value set in the application's env block. Returns
        `{ ok, errors: [...] }`. Works on any revision state."""
        revision: AgentRevision = self.get_object()
        report = self._call(_janitor().validate, str(revision.id))
        errors = list(report.get("errors", []))

        application = revision.application
        decrypted = application.encrypted_env or ""
        available_keys: set[str] = set()
        if decrypted:
            try:
                env_map = json.loads(decrypted)
                if isinstance(env_map, dict):
                    available_keys = {str(k) for k in env_map}
            except (ValueError, TypeError):
                pass
        for i, secret_name in enumerate(revision.spec.get("secrets") or []):
            if secret_name not in available_keys:
                errors.append(
                    {
                        "code": "missing_secret",
                        "message": f'secret "{secret_name}" is not set in the application env',
                        "pointer": f"spec.secrets[{i}]",
                    }
                )
        report["errors"] = errors
        report["ok"] = len(errors) == 0
        return Response(report)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"], url_path="freeze")
    def freeze(self, request: Request, **kwargs) -> Response:
        """Freeze the bundle: draft → ready, stamps sha256 on the row.
        The janitor computes the digest and updates the revision row in PG;
        Django re-reads the row before returning so the response reflects
        the persisted state."""
        revision: AgentRevision = self.get_object()
        result = self._call(_janitor().freeze, str(revision.id))
        revision.refresh_from_db()
        return Response(
            {
                **result,
                "revision": AgentRevisionSerializer(revision).data,
            }
        )

    @extend_schema(request=CloneFromRequestSerializer)
    @action(detail=True, methods=["post"], url_path="clone_from")
    def clone_from(self, request: Request, **kwargs) -> Response:
        """Copy every file from `source_revision_id` into this revision."""
        revision: AgentRevision = self.get_object()
        body = CloneFromRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        source_id = str(body.validated_data["source_revision_id"])
        # Guard against cross-app cloning — the source must belong to the same
        # team. The janitor doesn't enforce this since it trusts Django.
        source = AgentRevision.objects.filter(application__team_id=self.team_id, pk=source_id).first()
        if source is None:
            raise NotFound("Source revision not found in this team.")
        return Response(self._call(_janitor().clone_from, str(revision.id), source_id))

    @extend_schema(request=NewDraftRevisionRequestSerializer)
    @action(detail=False, methods=["post"], url_path="new_draft")
    def new_draft(self, request: Request, **kwargs) -> Response:
        """Create a fresh draft revision under `application_id` and seed it
        from `source_revision_id`. Saves the MCP one round-trip vs the
        explicit create + clone_from sequence."""
        body = NewDraftRevisionRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        application_id = str(body.validated_data["application_id"])
        source_id = str(body.validated_data["source_revision_id"])

        application = AgentApplication.objects.filter(team_id=self.team_id, pk=application_id, archived=False).first()
        if application is None:
            raise NotFound("Application not found in this team.")
        source = AgentRevision.objects.filter(application__team_id=self.team_id, pk=source_id).first()
        if source is None:
            raise NotFound("Source revision not found in this team.")

        # bundle_uri convention: the runner-side bundle store resolves this.
        # In dev/CI we use a filesystem prefix derived from the app + new
        # revision id; prod swaps in the team's S3 prefix at deploy time.
        draft = AgentRevision.objects.create(
            application=application,
            parent_revision=source,
            created_by=self.request.user,
            state="draft",
            bundle_uri=source.bundle_uri,  # same bundle root; janitor scopes by revision_id
            spec=source.spec,
        )
        self._call(_janitor().clone_from, str(draft.id), source_id)
        return Response(
            {
                "revision": AgentRevisionSerializer(draft).data,
                "source_revision_id": source_id,
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["agent_stack"])
class AgentNativeToolsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read-only catalog of every `@posthog/*` native tool the runner knows.

    URLs:
        GET /api/projects/<team>/agent_native_tools/    — list

    Backed by the janitor (which imports `listNativeTools()` from
    `@posthog/agent-tools`). Keeps a single source of truth for what tools
    exist — agents can't put unknown tool ids in their spec, and the MCP /
    wizard show this list to humans + models when picking what to wire up.
    """

    scope_object = "agent_application"
    scope_object_read_actions = ["list"]

    @extend_schema(
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentNativeToolsListResponse",
                fields={
                    "tools": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentNativeToolEntry",
                            fields={
                                "id": drf_serializers.CharField(),
                                "schema": drf_serializers.DictField(),
                            },
                        ),
                    ),
                },
            )
        ),
        description="Read-only catalog of every @posthog/* native tool the runner knows.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        try:
            return Response(_janitor().native_tools())
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e


# Suppress unused-import warning for the type re-export below.
_ = EncryptedTextField
