from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.insight_variable import InsightVariable


class InsightVariableSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsightVariable

        fields = ["id", "name", "type", "default_value", "created_by", "created_at", "code_name"]

        read_only_fields = ["id", "code_name", "created_by", "created_at"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        # Strips non alphanumeric values from name (other than spaces)
        validated_data["code_name"] = (
            "".join(n for n in validated_data["name"] if n.isalnum() or n == " ").replace(" ", "_").lower()
        )

        return InsightVariable.objects.create(**validated_data)


class InsightVariableViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = InsightVariable.objects.all()
    serializer_class = InsightVariableSerializer
    filter_backends = [DjangoFilterBackend]
