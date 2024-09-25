from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.insight_variable import InsightVariable


class InsightVariableSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsightVariable

        fields = ["id", "name", "type", "default_value", "created_by", "created_at"]

        read_only_fields = ["id", "created_by", "created_at"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        return InsightVariable.objects.create(**validated_data)


class InsightVariableViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = InsightVariable.objects.all()
    serializer_class = InsightVariableSerializer
    filter_backends = [DjangoFilterBackend]
