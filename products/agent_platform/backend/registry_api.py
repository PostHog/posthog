"""
DRF viewsets for the Tools & Skills registry.

Two parallel families — `AgentSkillTemplateViewSet` and
`AgentCustomToolTemplateViewSet`. Each one mirrors the `LLMSkill`
viewset shape on the ai_observability side: list / retrieve / publish
/ archive / duplicate / versions / usages, plus file CRUD for skill
templates. Same access-control + scope pattern as the rest of
`agent_platform`.

Spec → bundle wiring (the freeze-time copy + join row inserts) is in
`registry_freeze.py`. Native tools have their own existing viewset in
`api.py` (`AgentNativeToolsViewSet`); the registry just reads from it
through the same Django proxy.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F, Q, QuerySet

from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import (
    mixins,
    serializers as drf_serializers,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from .models import (
    AgentCustomToolTemplate,
    AgentRevisionCustomToolTemplate,
    AgentRevisionSkillTemplate,
    AgentSkillTemplate,
    AgentSkillTemplateFile,
)
from .registry_edits import StructuredEditError, apply_structured_edits
from .registry_serializers import (
    CANONICAL_NAME_REGEX,
    CustomToolTemplateCreateSerializer,
    CustomToolTemplateDetailSerializer,
    CustomToolTemplateDuplicateSerializer,
    CustomToolTemplatePublishSerializer,
    CustomToolTemplateSummarySerializer,
    CustomToolTemplateUsageSerializer,
    SkillTemplateCreateSerializer,
    SkillTemplateDetailSerializer,
    SkillTemplateDuplicateSerializer,
    SkillTemplateFileRenameSerializer,
    SkillTemplateFileSerializer,
    SkillTemplateFileWriteSerializer,
    SkillTemplatePublishSerializer,
    SkillTemplateSummarySerializer,
    SkillTemplateUsageSerializer,
    TemplateVersionEntrySerializer,
)

# ───────────────────────────── Skill templates ──────────────────────────────


@extend_schema(tags=["agent_platform"])
class AgentSkillTemplateViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Shared, versioned markdown skill templates.

    URLs:
        GET    /api/projects/<team>/agent_skill_templates/
        POST   /api/projects/<team>/agent_skill_templates/
        GET    /api/projects/<team>/agent_skill_templates/name/<name>/
        POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
        POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
        POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
        GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
        GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
        POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
        DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
        POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

    Canonical (`@posthog/<name>`) templates are read-only for team
    members; only PostHog-side seed commands write them.
    """

    # Class-level serializer keeps drf-spectacular from warning during schema
    # generation — every action declares its own request/response shape via
    # `@extend_schema`, so this is just the catch-all fallback.
    serializer_class = SkillTemplateDetailSerializer
    scope_object = "agents"
    scope_object_read_actions = ["list", "retrieve_by_name", "versions", "usages"]
    scope_object_write_actions = [
        "create",
        "publish",
        "archive",
        "duplicate",
        "create_file",
        "delete_file",
        "rename_file",
    ]
    lookup_field = "name"

    # ---- queryset / lookup helpers ----

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:  # type: ignore[override]
        # Templates either belong to the active team or are canonical
        # (team_id IS NULL). Both surface in the registry list.
        return AgentSkillTemplate.objects.filter(
            deleted=False,
        ).filter(models_q_team_or_canonical(self.team_id))

    def _latest_by_name(self, name: str) -> AgentSkillTemplate:
        qs = self.safely_get_queryset(AgentSkillTemplate.objects.all()).filter(name=name, is_latest=True)
        obj = qs.first()
        if not obj:
            raise NotFound(f"Skill template {name!r} not found.")
        return obj

    def _at_version(self, name: str, version: int) -> AgentSkillTemplate:
        qs = self.safely_get_queryset(AgentSkillTemplate.objects.all()).filter(name=name, version=version)
        obj = qs.first()
        if not obj:
            raise NotFound(f"Skill template {name!r} v{version} not found.")
        return obj

    def _ensure_writable(self, name: str) -> None:
        if CANONICAL_NAME_REGEX.match(name):
            raise ValidationError("Canonical `@posthog/*` templates are read-only for teams. Use the seed command.")

    # ---- list ----

    @extend_schema(
        summary="List the latest version of every skill template visible to the team.",
        parameters=[
            OpenApiParameter(
                "search",
                str,
                required=False,
                description="Optional substring filter against name + description.",
            ),
        ],
        responses=SkillTemplateSummarySerializer(many=True),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        qs = self.safely_get_queryset(AgentSkillTemplate.objects.all()).filter(is_latest=True).order_by("name")
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(models_q_name_or_description(search))
        return Response(SkillTemplateSummarySerializer(qs, many=True).data)

    # ---- retrieve by name (with optional ?version=N) ----

    @extend_schema(
        summary="Retrieve a skill template's latest version, or a specific version with `?version=N`.",
        parameters=[
            OpenApiParameter(
                "version",
                int,
                required=False,
                description="Fetch a specific version. Omit for the current `is_latest=true` row.",
            ),
        ],
        responses=SkillTemplateDetailSerializer,
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<name>[^/]+)")
    def retrieve_by_name(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        version_param = request.query_params.get("version")
        if version_param is not None:
            try:
                version = int(version_param)
            except ValueError as exc:
                raise ValidationError("`version` must be an integer.") from exc
            obj = self._at_version(name, version)
        else:
            obj = self._latest_by_name(name)
        return Response(SkillTemplateDetailSerializer(obj).data)

    # ---- create (v1) ----

    @extend_schema(
        summary="Create a new skill template — produces v1.",
        request=SkillTemplateCreateSerializer,
        responses={201: SkillTemplateDetailSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = SkillTemplateCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        self._ensure_writable(data["name"])
        # Existence check (case-sensitive — slugs are lowercased anyway).
        if AgentSkillTemplate.objects.filter(team_id=self.team_id, name=data["name"], deleted=False).exists():
            raise ValidationError(f"A skill template named {data['name']!r} already exists.")

        with transaction.atomic():
            template = AgentSkillTemplate.objects.create(
                team_id=self.team_id,
                name=data["name"],
                description=data["description"],
                body=data["body"],
                license=data["license"],
                compatibility=data["compatibility"],
                metadata=data["metadata"],
                allowed_tools=data["allowed_tools"],
                version=1,
                is_latest=True,
                created_by=request.user if request.user.is_authenticated else None,
            )
            for file in data["files"]:
                AgentSkillTemplateFile.objects.create(
                    template=template,
                    path=file["path"],
                    content=file["content"],
                    content_type=file.get("content_type", "text/plain"),
                )
        return Response(SkillTemplateDetailSerializer(template).data, status=status.HTTP_201_CREATED)

    # ---- publish (new version) ----

    @extend_schema(
        summary="Publish a new version of the named template.",
        request=SkillTemplatePublishSerializer,
        responses=SkillTemplateDetailSerializer,
    )
    @action(methods=["POST"], detail=False, url_path=r"name/(?P<name>[^/]+)/publish")
    def publish(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        self._ensure_writable(name)
        prior = self._latest_by_name(name)

        body = SkillTemplatePublishSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        if "body" in data:
            new_body = data["body"]
        elif data.get("edits"):
            try:
                new_body = apply_structured_edits(prior.body, list(data["edits"]))
            except StructuredEditError as e:
                # drf-exceptions-hog only forwards extra fields via `exc.extra`.
                err = ValidationError(e.message)
                err.extra = {"edit_index": e.edit_index}  # type: ignore[attr-defined]
                raise err from e

        with transaction.atomic():
            AgentSkillTemplate.objects.filter(pk=prior.pk).update(is_latest=False)
            next_template = AgentSkillTemplate.objects.create(
                team=prior.team,
                name=prior.name,
                description=data.get("description", prior.description),
                body=new_body,
                license=data.get("license", prior.license),
                compatibility=data.get("compatibility", prior.compatibility),
                metadata=data.get("metadata", prior.metadata),
                allowed_tools=data.get("allowed_tools", prior.allowed_tools),
                version=prior.version + 1,
                is_latest=True,
                created_by=request.user if request.user.is_authenticated else None,
            )
            # Copy companion files forward — publish without explicit file
            # edits carries the prior files unchanged.
            for f in prior.files.all():
                AgentSkillTemplateFile.objects.create(
                    template=next_template,
                    path=f.path,
                    content=f.content,
                    content_type=f.content_type,
                )
        return Response(SkillTemplateDetailSerializer(next_template).data)

    # ---- archive (soft delete) ----

    @extend_schema(summary="Soft-delete all versions of a template.", responses={204: None})
    @action(methods=["POST"], detail=False, url_path=r"name/(?P<name>[^/]+)/archive")
    def archive(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        self._ensure_writable(name)
        AgentSkillTemplate.objects.filter(team_id=self.team_id, name=name).update(deleted=True, is_latest=False)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ---- duplicate ----

    @extend_schema(
        summary="Duplicate a template under a new name (clones the latest version's content + files).",
        request=SkillTemplateDuplicateSerializer,
        responses={201: SkillTemplateDetailSerializer},
    )
    @action(methods=["POST"], detail=False, url_path=r"name/(?P<name>[^/]+)/duplicate")
    def duplicate(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        source = self._latest_by_name(name)

        body = SkillTemplateDuplicateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        self._ensure_writable(data["name"])

        if AgentSkillTemplate.objects.filter(team_id=self.team_id, name=data["name"], deleted=False).exists():
            raise ValidationError(f"A skill template named {data['name']!r} already exists.")

        with transaction.atomic():
            duplicate = AgentSkillTemplate.objects.create(
                team_id=self.team_id,
                name=data["name"],
                description=data.get("description", source.description),
                body=source.body,
                license=source.license,
                compatibility=source.compatibility,
                metadata=source.metadata,
                allowed_tools=source.allowed_tools,
                version=1,
                is_latest=True,
                created_by=request.user if request.user.is_authenticated else None,
            )
            for f in source.files.all():
                AgentSkillTemplateFile.objects.create(
                    template=duplicate,
                    path=f.path,
                    content=f.content,
                    content_type=f.content_type,
                )
        return Response(SkillTemplateDetailSerializer(duplicate).data, status=status.HTTP_201_CREATED)

    # ---- versions ----

    @extend_schema(
        summary="List every version of the named template, newest first.",
        responses=TemplateVersionEntrySerializer(many=True),
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<name>[^/]+)/versions")
    def versions(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        # Touch the latest first so 404 fires for non-existent templates.
        self._latest_by_name(name)
        qs = (
            self.safely_get_queryset(AgentSkillTemplate.objects.all())
            .filter(name=name)
            .order_by("-version")
            .select_related("created_by")
        )
        return Response(TemplateVersionEntrySerializer(qs, many=True).data)

    # ---- usages (join table) ----

    @extend_schema(
        summary="List the frozen agent revisions pinning this template (any version, or filtered by `pinned_version`).",
        parameters=[
            OpenApiParameter(
                "pinned_version",
                int,
                required=False,
                description="Filter to revisions stuck on a specific version (`/?pinned_version=3`).",
            ),
        ],
        responses=SkillTemplateUsageSerializer(many=True),
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<name>[^/]+)/usages")
    def usages(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        self._latest_by_name(name)
        qs = AgentRevisionSkillTemplate.objects.filter(
            skill_template__name=name,
            skill_template__team_id=self.team_id,
        ).select_related("revision__application")
        version_param = request.query_params.get("pinned_version")
        if version_param is not None:
            try:
                qs = qs.filter(pinned_version=int(version_param))
            except ValueError as exc:
                raise ValidationError("`pinned_version` must be an integer.") from exc
        data = [
            {
                "agent_slug": row.revision.application.slug,
                "agent_name": row.revision.application.name,
                "revision_id": row.revision.id,
                "revision_short_id": str(row.revision.id)[:8],
                "pinned_version": row.pinned_version,
            }
            for row in qs
        ]
        return Response(SkillTemplateUsageSerializer(data, many=True).data)

    # ---- file CRUD ----

    @extend_schema(
        summary="Add a companion file to the latest version of the template.",
        request=SkillTemplateFileWriteSerializer,
        responses={201: SkillTemplateFileSerializer},
    )
    @action(methods=["POST"], detail=False, url_path=r"name/(?P<name>[^/]+)/files")
    def create_file(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        self._ensure_writable(name)
        template = self._latest_by_name(name)
        body = SkillTemplateFileWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            file = AgentSkillTemplateFile.objects.create(
                template=template,
                path=body.validated_data["path"],
                content=body.validated_data["content"],
                content_type=body.validated_data.get("content_type", "text/plain"),
            )
        except IntegrityError as e:
            raise ValidationError(f"A file at {body.validated_data['path']!r} already exists.") from e
        return Response(SkillTemplateFileSerializer(file).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Remove a companion file from the latest version of the template.",
        responses={204: None},
    )
    @action(
        methods=["DELETE"],
        detail=False,
        url_path=r"name/(?P<name>[^/]+)/files/(?P<file_path>.+?)",
    )
    def delete_file(self, request: Request, name: str = "", file_path: str = "", **kwargs: Any) -> Response:
        self._ensure_writable(name)
        template = self._latest_by_name(name)
        # The DRF router appends `/?$`; the non-greedy `.+?` keeps the
        # trailing slash out of `file_path` (otherwise the lookup misses).
        normalized = file_path.rstrip("/")
        deleted_count, _ = AgentSkillTemplateFile.objects.filter(template=template, path=normalized).delete()
        if deleted_count == 0:
            raise NotFound(f"No file at {normalized!r}.")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Rename a companion file inside the latest version of the template.",
        request=SkillTemplateFileRenameSerializer,
        responses=SkillTemplateFileSerializer,
    )
    @action(methods=["POST"], detail=False, url_path=r"name/(?P<name>[^/]+)/files-rename")
    def rename_file(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        self._ensure_writable(name)
        template = self._latest_by_name(name)
        body = SkillTemplateFileRenameSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        from_path = body.validated_data["from_path"]
        to_path = body.validated_data["to_path"]
        file = AgentSkillTemplateFile.objects.filter(template=template, path=from_path).first()
        if not file:
            raise NotFound(f"No file at {from_path!r}.")
        if AgentSkillTemplateFile.objects.filter(template=template, path=to_path).exists():
            raise ValidationError(f"A file at {to_path!r} already exists.")
        file.path = to_path
        file.save(update_fields=["path"])
        return Response(SkillTemplateFileSerializer(file).data)


# ─────────────────────────── Custom tool templates ──────────────────────────


@extend_schema(tags=["agent_platform"])
class AgentCustomToolTemplateViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Shared, versioned TypeScript custom tool templates.

    URLs:
        GET    /api/projects/<team>/agent_custom_tool_templates/
        POST   /api/projects/<team>/agent_custom_tool_templates/
        GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
        POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
        POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
        POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
        GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
        GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
    """

    serializer_class = CustomToolTemplateDetailSerializer
    scope_object = "agents"
    scope_object_read_actions = ["list", "retrieve_by_name", "versions", "usages"]
    scope_object_write_actions = ["create", "publish", "archive", "duplicate"]
    lookup_field = "name"

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:  # type: ignore[override]
        return AgentCustomToolTemplate.objects.filter(
            deleted=False,
        ).filter(models_q_team_or_canonical(self.team_id))

    def _latest_by_name(self, name: str) -> AgentCustomToolTemplate:
        qs = self.safely_get_queryset(AgentCustomToolTemplate.objects.all()).filter(name=name, is_latest=True)
        obj = qs.first()
        if not obj:
            raise NotFound(f"Custom tool template {name!r} not found.")
        return obj

    def _at_version(self, name: str, version: int) -> AgentCustomToolTemplate:
        qs = self.safely_get_queryset(AgentCustomToolTemplate.objects.all()).filter(name=name, version=version)
        obj = qs.first()
        if not obj:
            raise NotFound(f"Custom tool template {name!r} v{version} not found.")
        return obj

    def _ensure_writable(self, name: str) -> None:
        if CANONICAL_NAME_REGEX.match(name):
            raise ValidationError("Canonical `@posthog/*` tools are read-only for teams. Use the seed command.")

    # ---- list ----

    @extend_schema(
        summary="List the latest version of every custom tool template visible to the team.",
        parameters=[
            OpenApiParameter(
                "search", str, required=False, description="Optional substring filter against name + description."
            ),
        ],
        responses=CustomToolTemplateSummarySerializer(many=True),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        qs = self.safely_get_queryset(AgentCustomToolTemplate.objects.all()).filter(is_latest=True).order_by("name")
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(models_q_name_or_description(search))
        return Response(CustomToolTemplateSummarySerializer(qs, many=True).data)

    @extend_schema(
        summary="Retrieve a custom tool template's latest version, or a specific version with `?version=N`.",
        parameters=[
            OpenApiParameter("version", int, required=False, description="Fetch a specific version."),
        ],
        responses=CustomToolTemplateDetailSerializer,
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<name>[^/]+)")
    def retrieve_by_name(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        version_param = request.query_params.get("version")
        if version_param is not None:
            try:
                version = int(version_param)
            except ValueError as exc:
                raise ValidationError("`version` must be an integer.") from exc
            obj = self._at_version(name, version)
        else:
            obj = self._latest_by_name(name)
        return Response(CustomToolTemplateDetailSerializer(obj).data)

    @extend_schema(
        summary="Create a new custom tool template — produces v1.",
        request=CustomToolTemplateCreateSerializer,
        responses={201: CustomToolTemplateDetailSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = CustomToolTemplateCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        self._ensure_writable(data["name"])
        if AgentCustomToolTemplate.objects.filter(team_id=self.team_id, name=data["name"], deleted=False).exists():
            raise ValidationError(f"A custom tool template named {data['name']!r} already exists.")

        template = AgentCustomToolTemplate.objects.create(
            team_id=self.team_id,
            name=data["name"],
            description=data["description"],
            source=data["source"],
            compiled_js=data["compiled_js"],
            args_schema=data["args_schema"],
            returns_schema=data.get("returns_schema") or {},
            requires_secrets=list(data["requires_secrets"]),
            version=1,
            is_latest=True,
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(CustomToolTemplateDetailSerializer(template).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Publish a new version of the named custom tool template.",
        request=CustomToolTemplatePublishSerializer,
        responses=CustomToolTemplateDetailSerializer,
    )
    @action(methods=["POST"], detail=False, url_path=r"name/(?P<name>[^/]+)/publish")
    def publish(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        self._ensure_writable(name)
        prior = self._latest_by_name(name)

        body = CustomToolTemplatePublishSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        if "source" in data:
            new_source = data["source"]
        elif data.get("edits"):
            try:
                new_source = apply_structured_edits(prior.source, list(data["edits"]))
            except StructuredEditError as e:
                err = ValidationError(e.message)
                err.extra = {"edit_index": e.edit_index}  # type: ignore[attr-defined]
                raise err from e
        else:
            new_source = prior.source

        with transaction.atomic():
            AgentCustomToolTemplate.objects.filter(pk=prior.pk).update(is_latest=False)
            next_template = AgentCustomToolTemplate.objects.create(
                team=prior.team,
                name=prior.name,
                description=data.get("description", prior.description),
                source=new_source,
                compiled_js=data.get("compiled_js", prior.compiled_js),
                args_schema=data.get("args_schema", prior.args_schema),
                returns_schema=data.get("returns_schema", prior.returns_schema),
                requires_secrets=list(data.get("requires_secrets", prior.requires_secrets)),
                version=prior.version + 1,
                is_latest=True,
                created_by=request.user if request.user.is_authenticated else None,
            )
        return Response(CustomToolTemplateDetailSerializer(next_template).data)

    @extend_schema(summary="Soft-delete all versions of a custom tool template.", responses={204: None})
    @action(methods=["POST"], detail=False, url_path=r"name/(?P<name>[^/]+)/archive")
    def archive(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        self._ensure_writable(name)
        AgentCustomToolTemplate.objects.filter(team_id=self.team_id, name=name).update(deleted=True, is_latest=False)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Duplicate a custom tool template under a new name.",
        request=CustomToolTemplateDuplicateSerializer,
        responses={201: CustomToolTemplateDetailSerializer},
    )
    @action(methods=["POST"], detail=False, url_path=r"name/(?P<name>[^/]+)/duplicate")
    def duplicate(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        source = self._latest_by_name(name)
        body = CustomToolTemplateDuplicateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        self._ensure_writable(data["name"])
        if AgentCustomToolTemplate.objects.filter(team_id=self.team_id, name=data["name"], deleted=False).exists():
            raise ValidationError(f"A custom tool template named {data['name']!r} already exists.")
        duplicate = AgentCustomToolTemplate.objects.create(
            team_id=self.team_id,
            name=data["name"],
            description=data.get("description", source.description),
            source=source.source,
            compiled_js=source.compiled_js,
            args_schema=source.args_schema,
            returns_schema=source.returns_schema,
            requires_secrets=list(source.requires_secrets),
            version=1,
            is_latest=True,
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(CustomToolTemplateDetailSerializer(duplicate).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="List every version of the named custom tool template, newest first.",
        responses=TemplateVersionEntrySerializer(many=True),
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<name>[^/]+)/versions")
    def versions(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        self._latest_by_name(name)
        qs = (
            self.safely_get_queryset(AgentCustomToolTemplate.objects.all())
            .filter(name=name)
            .order_by("-version")
            .select_related("created_by")
        )
        return Response(TemplateVersionEntrySerializer(qs, many=True).data)

    @extend_schema(
        summary="List the frozen agent revisions pinning this custom tool template.",
        parameters=[
            OpenApiParameter("pinned_version", int, required=False, description="Filter to a specific pinned version."),
        ],
        responses=CustomToolTemplateUsageSerializer(many=True),
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<name>[^/]+)/usages")
    def usages(self, request: Request, name: str = "", **kwargs: Any) -> Response:
        self._latest_by_name(name)
        qs = AgentRevisionCustomToolTemplate.objects.filter(
            tool_template__name=name,
            tool_template__team_id=self.team_id,
        ).select_related("revision__application")
        version_param = request.query_params.get("pinned_version")
        if version_param is not None:
            try:
                qs = qs.filter(pinned_version=int(version_param))
            except ValueError as exc:
                raise ValidationError("`pinned_version` must be an integer.") from exc
        data = [
            {
                "agent_slug": row.revision.application.slug,
                "agent_name": row.revision.application.name,
                "revision_id": row.revision.id,
                "revision_short_id": str(row.revision.id)[:8],
                "pinned_version": row.pinned_version,
            }
            for row in qs
        ]
        return Response(CustomToolTemplateUsageSerializer(data, many=True).data)


# ─── small Q-object helpers (kept inline to avoid a third module) ───────────


def models_q_team_or_canonical(team_id: int) -> Any:
    """Filter: belongs to this team OR is canonical (team_id IS NULL)."""
    return Q(team_id=team_id) | Q(team_id__isnull=True)


def models_q_name_or_description(search: str) -> Any:
    """Substring filter against name + description (case-insensitive)."""
    return Q(name__icontains=search) | Q(description__icontains=search)


# Suppress unused-import warning for `mixins` / `inline_serializer` / `F` —
# placeholders the next iteration will pick up when fleshing the response
# shapes of `archive` / `duplicate`.
_ = (mixins, inline_serializer, F, drf_serializers)
