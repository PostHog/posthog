from typing import Any, Dict

from rest_framework import authentication, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings

from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import JwtAuthentication, PersonalAPIKeyAuthentication
from posthog.models import DatabaseTable, DatabaseField
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class DatabaseFieldSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=False, required=False)

    class Meta:
        model = DatabaseField
        fields = [
            "id",
            "name",
            "type",
        ]


class DatabaseTableSerializer(serializers.ModelSerializer):
    fields = DatabaseFieldSerializer(many=True, required=False)

    class Meta:
        model = DatabaseTable
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
            DatabaseField.objects.create(
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
                    field_instance = DatabaseField.objects.get(pk=field["id"])
                    field_serializer = DatabaseFieldSerializer(instance=field_instance)
                    field_serializer.update(field_instance, field)
                else:
                    DatabaseField.objects.create(
                        table=instance,
                        team_id=self.context["team_id"],
                        **{key: value for key, value in field.items()},
                    )

        instance = super().update(instance, validated_data)
        instance.refresh_from_db()
        return instance


class DatabaseTableViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES)
    queryset = DatabaseTable.objects.all()
    serializer_class = DatabaseTableSerializer
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
