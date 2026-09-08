from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.entity_dependencies.models import EntityDependency
from posthog.models.entity_dependencies.registry import resolve_references
from posthog.models.entity_dependencies.types import EntityRefStatus

# Bounds each group so one heavily referenced entity cannot make the response unbounded.
DEPENDENCY_GROUP_PAGE_SIZE = 100


class EntityRefSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Registry entity type, for example 'cohort' or 'hog_flow'.")
    id = serializers.CharField(help_text="Entity id as a string. Sources and targets mix integer and UUID keys.")
    name = serializers.CharField(
        allow_blank=True, help_text="Display name from the owning product. Empty when unresolved or unnamed."
    )
    url = serializers.CharField(allow_blank=True, help_text="App path to the entity. Empty when unresolved.")
    status = serializers.ChoiceField(
        choices=EntityRefStatus.choices,
        help_text=(
            "Resolution state: 'active' or 'archived' when the entity exists, 'deleted' when soft-deleted, "
            "'missing' when the id resolves to nothing, 'unknown' when no resolver is registered for the type."
        ),
    )


class EntityDependencyEntrySerializer(serializers.Serializer):
    entity = EntityRefSerializer(help_text="The referenced or referencing entity, resolved for display.")
    roles = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Source-defined labels for how the reference is used, for example 'trigger_audience'. "
            "A 'draft:' prefix marks references that exist only in unpublished draft content."
        ),
    )


class EntityDependencyGroupSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Entity type shared by every entry in this group.")
    total = serializers.IntegerField(help_text="Total number of related entities of this type.")
    has_more = serializers.BooleanField(help_text="True when results were capped and more entities exist.")
    results = EntityDependencyEntrySerializer(many=True, help_text="Related entities, capped per group.")


@extend_schema(tags=["dependencies"], extensions={"x-product": "core"})
class EntityDependencyViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read side of the entity dependency registry: what references an entity, and what an entity references."""

    scope_object = "INTERNAL"

    @extend_schema(
        summary="List an entity's dependencies",
        description=(
            "Lists recorded references between entities. Pass target_type and target_id to ask what "
            "references an entity (for example, the workflows that use a cohort), or source_type and "
            "source_id to ask what an entity references (for example, the cohorts a workflow uses). "
            "Exactly one of the two pairs is required. Returns one group per related entity type. "
            "References are recorded by each product when its entities are saved; entities of types "
            "without a registered resolver come back id-only with status 'unknown'."
        ),
        parameters=[
            OpenApiParameter(
                name="target_type",
                type=str,
                required=False,
                description="Entity type to list referencing entities for. Requires target_id.",
            ),
            OpenApiParameter(
                name="target_id",
                type=str,
                required=False,
                description="Entity id to list referencing entities for. Requires target_type.",
            ),
            OpenApiParameter(
                name="source_type",
                type=str,
                required=False,
                description="Entity type to list referenced entities for. Requires source_id.",
            ),
            OpenApiParameter(
                name="source_id",
                type=str,
                required=False,
                description="Entity id to list referenced entities for. Requires source_type.",
            ),
        ],
        responses={200: EntityDependencyGroupSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        target_type = request.GET.get("target_type", "")
        target_id = request.GET.get("target_id", "")
        source_type = request.GET.get("source_type", "")
        source_id = request.GET.get("source_id", "")

        asks_target = bool(target_type or target_id)
        asks_source = bool(source_type or source_id)
        if asks_target == asks_source:
            raise ValidationError("Pass either target_type and target_id, or source_type and source_id.")
        if asks_target and not (target_type and target_id):
            raise ValidationError("target_type and target_id are both required.")
        if asks_source and not (source_type and source_id):
            raise ValidationError("source_type and source_id are both required.")

        if asks_target:
            rows = EntityDependency.objects.filter(target_type=target_type, target_id=target_id)
            row_key = ("source_type", "source_id")
        else:
            rows = EntityDependency.objects.filter(source_type=source_type, source_id=source_id)
            row_key = ("target_type", "target_id")

        roles_by_entity: dict[tuple[str, str], set[str]] = {}
        for row in rows.only("source_type", "source_id", "target_type", "target_id", "role"):
            key = (getattr(row, row_key[0]), getattr(row, row_key[1]))
            roles_by_entity.setdefault(key, set()).add(row.role)

        ids_by_type: dict[str, list[str]] = {}
        for entity_type, entity_id in roles_by_entity:
            ids_by_type.setdefault(entity_type, []).append(entity_id)

        groups = []
        for entity_type in sorted(ids_by_type):
            refs = resolve_references(self.team_id, entity_type, ids_by_type[entity_type])
            entries = sorted(refs.values(), key=lambda ref: (ref.name.lower(), ref.id))
            groups.append(
                {
                    "type": entity_type,
                    "total": len(entries),
                    "has_more": len(entries) > DEPENDENCY_GROUP_PAGE_SIZE,
                    "results": [
                        {"entity": ref, "roles": sorted(roles_by_entity[(entity_type, ref.id)])}
                        for ref in entries[:DEPENDENCY_GROUP_PAGE_SIZE]
                    ],
                }
            )

        return Response(EntityDependencyGroupSerializer(groups, many=True).data)
