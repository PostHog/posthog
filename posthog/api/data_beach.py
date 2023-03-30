import json
from typing import Any, Dict

from rest_framework import authentication, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import JwtAuthentication, PersonalAPIKeyAuthentication
from posthog.clickhouse.client import sync_execute
from posthog.models import DataBeachTable, DataBeachField
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class DataBeachFieldSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=False, required=False)

    class Meta:
        model = DataBeachField
        fields = [
            "id",
            "name",
            "type",
        ]


class DataBeachTableSerializer(serializers.ModelSerializer):
    fields = DataBeachFieldSerializer(many=True, required=False)

    class Meta:
        model = DataBeachTable
        fields = [
            "id",
            "name",
            "engine",
            "fields",
        ]

    def create(self, validated_data: Any) -> Any:
        fields = validated_data.pop("fields", [])
        validated_data["team_id"] = self.context["team_id"]
        instance = super().create(validated_data)
        for field in fields:
            DataBeachField.objects.create(
                table=instance,
                team_id=self.context["team_id"],
                **{key: value for key, value in field.items()},
            )
        return instance

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        fields = validated_data.pop("fields", None)
        # If there's no fields property at all we just ignore it
        # If there is a field property but it's an empty array [], we'll delete all the fields
        if fields is not None:
            # remove fields not in the request
            field_ids = [field["id"] for field in fields if field.get("id")]
            instance.fields.exclude(pk__in=field_ids).delete()

            for field in fields:
                if field.get("id"):
                    field_instance = DataBeachField.objects.get(pk=field["id"])
                    field_serializer = DataBeachFieldSerializer(instance=field_instance)
                    field_serializer.update(field_instance, field)
                else:
                    DataBeachField.objects.create(
                        table=instance,
                        team_id=self.context["team_id"],
                        **{key: value for key, value in field.items()},
                    )

        instance = super().update(instance, validated_data)
        instance.refresh_from_db()
        return instance


class DataBeachTableViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES)
    queryset = DataBeachTable.objects.all()
    serializer_class = DataBeachTableSerializer
    authentication_classes = [
        JwtAuthentication,
        PersonalAPIKeyAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(team_id=self.team_id).prefetch_related("fields")

    @action(methods=["POST"], detail=True)
    def insert_data(self, request, **kwargs):
        data_beach_table = self.get_object()

        for row in request.data:
            sync_execute(
                """
                INSERT INTO data_beach_appendable (
                    team_id,
                    table_name,
                    id,
                    data
                ) VALUES
            """,
                [(self.team_id, data_beach_table.name, "", json.dumps(row))],
            )
        return Response({"success": True})
