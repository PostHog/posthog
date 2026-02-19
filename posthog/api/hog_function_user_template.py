from typing import Optional, cast

from django.db.models import Q

import structlog
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.hog_functions.hog_function_user_template import HogFunctionUserTemplate
from posthog.models.organization import OrganizationMembership

logger = structlog.get_logger(__name__)


class HogFunctionUserTemplateSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = HogFunctionUserTemplate
        fields = [
            "id",
            "name",
            "description",
            "icon_url",
            "tags",
            "scope",
            "created_at",
            "created_by",
            "updated_at",
            "type",
            "hog",
            "inputs_schema",
            "inputs",
            "filters",
            "mappings",
            "masking",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

    def get_created_by(self, obj: HogFunctionUserTemplate) -> Optional[dict]:
        if obj.created_by:
            from posthog.api.shared import UserBasicSerializer

            return UserBasicSerializer(obj.created_by).data
        return None

    def validate(self, data: dict) -> dict:
        instance = cast(Optional[HogFunctionUserTemplate], self.instance)

        name = data.get("name")
        if name is None:
            if not instance or not instance.name:
                raise serializers.ValidationError({"name": "Name is required"})
        elif not name.strip():
            raise serializers.ValidationError({"name": "Name cannot be empty"})

        if not data.get("hog") and not (instance and instance.hog):
            raise serializers.ValidationError({"hog": "Hog code is required"})

        if not data.get("type") and not (instance and instance.type):
            raise serializers.ValidationError({"type": "Type is required"})

        scope = data.get("scope", instance.scope if instance else HogFunctionUserTemplate.Scope.ONLY_TEAM)
        if scope == HogFunctionUserTemplate.Scope.ORGANIZATION:
            request = self.context.get("request")
            organization = self.context.get("organization")
            if request and organization:
                membership = OrganizationMembership.objects.filter(organization=organization, user=request.user).first()
                if not membership or membership.level < OrganizationMembership.Level.ADMIN:
                    raise serializers.ValidationError(
                        {"scope": "Organization-scoped templates require organization admin permissions"}
                    )

        return data

    def create(self, validated_data: dict, *args, **kwargs) -> HogFunctionUserTemplate:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        if not validated_data.get("scope"):
            validated_data["scope"] = HogFunctionUserTemplate.Scope.ONLY_TEAM
        return super().create(validated_data=validated_data)


class HogFunctionUserTemplateViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = HogFunctionUserTemplate.objects.all()
    serializer_class = HogFunctionUserTemplateSerializer

    def dangerously_get_queryset(self):
        qs = HogFunctionUserTemplate.objects.filter(
            Q(team_id=self.team_id)
            | Q(scope=HogFunctionUserTemplate.Scope.ORGANIZATION, team__organization_id=self.organization.id)
        )

        if self.action == "list":
            qs = qs.order_by("-updated_at")

        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["organization"] = self.organization
        return context

    def perform_update(self, serializer):
        serializer.validated_data["team_id"] = self.team_id
        serializer.save()

    @action(methods=["POST"], detail=False)
    def from_function(self, request: Request, *args, **kwargs) -> Response:
        """Create a user template from an existing HogFunction."""
        function_id = request.data.get("hog_function_id")
        if not function_id:
            raise serializers.ValidationError({"hog_function_id": "Required"})

        try:
            hog_function = HogFunction.objects.get(id=function_id, team_id=self.team_id, deleted=False)
        except HogFunction.DoesNotExist:
            raise serializers.ValidationError({"hog_function_id": "HogFunction not found"})

        template_data = {
            "name": request.data.get("name", hog_function.name or ""),
            "description": request.data.get("description", hog_function.description or ""),
            "icon_url": hog_function.icon_url,
            "type": hog_function.type or "transformation",
            "hog": hog_function.hog,
            "inputs_schema": hog_function.inputs_schema or [],
            "inputs": hog_function.inputs,
            "filters": hog_function.filters,
            "mappings": hog_function.mappings,
            "masking": hog_function.masking,
            "scope": request.data.get("scope", HogFunctionUserTemplate.Scope.ONLY_TEAM),
            "tags": request.data.get("tags", []),
        }

        serializer = self.get_serializer(data=template_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=201)
