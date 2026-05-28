"""
DRF viewsets for agent_stack — the authoring surface.

Covers the core agent-meta CRUD that the MCP / frontend wizard will hit:
    AgentApplicationViewSet   list / retrieve / create / update / destroy / set_env
    AgentRevisionViewSet      list / retrieve / create (draft) / update_spec /
                              promote / archive

Bundle-upload (presigned-URL flow) + manifest-preview are deferred to the
MCP redesign (TODO B5 in services/agent-shared/TODO.md). Sessions live in
the node-managed runtime DB and are not exposed through Django — point
session-list consumers at the janitor's `/sessions/:id` instead.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.encrypted_fields import EncryptedTextField

from .models import AgentApplication, AgentRevision
from .serializers import (
    AgentApplicationSerializer,
    AgentRevisionSerializer,
    PromoteRevisionRequestSerializer,
    SetEnvRequestSerializer,
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
    scope_object_read_actions = ["list", "retrieve"]
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


class AgentRevisionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Revisions of an agent. Created in `draft`, promoted through
    `ready → live` once the bundle has been uploaded + frozen.

    URLs (nested under an application):
        GET   /api/projects/<team>/agent_applications/<app>/revisions/
        POST  /api/projects/<team>/agent_applications/<app>/revisions/
        GET   /api/projects/<team>/agent_applications/<app>/revisions/<id>/
        PATCH /api/projects/<team>/agent_applications/<app>/revisions/<id>/
        POST  /api/projects/<team>/agent_applications/<app>/revisions/<id>/promote/
        POST  /api/projects/<team>/agent_applications/<app>/revisions/<id>/archive/
    """

    scope_object = "agent_application"  # share the parent's scope
    scope_object_write_actions = ["create", "update", "partial_update", "promote", "archive"]
    scope_object_read_actions = ["list", "retrieve"]
    serializer_class = AgentRevisionSerializer
    queryset = AgentRevision.objects.all()

    def get_application(self) -> AgentApplication:
        app = _resolve_application(
            AgentApplication.objects.filter(team_id=self.team_id, archived=False),
            self.kwargs.get("application_id") or self.kwargs.get("parent_lookup_application"),
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


# Suppress unused-import warning for the type re-export below.
_ = EncryptedTextField
