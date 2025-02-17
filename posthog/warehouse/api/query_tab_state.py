from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.warehouse.models import QueryTabState


class QueryTabStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = QueryTabState
        fields = ["id", "state"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        query_tab_state = QueryTabState(**validated_data)
        query_tab_state.save()
        return query_tab_state


class QueryTabStateViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Query Tab State.
    """

    scope_object = "INTERNAL"
    queryset = QueryTabState.objects.all()
    serializer_class = QueryTabStateSerializer

    def safely_get_queryset(self, queryset):
        return queryset.exclude(deleted=True)
