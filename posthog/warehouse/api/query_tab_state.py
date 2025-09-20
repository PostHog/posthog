from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
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

    @action(detail=False, methods=["get"])
    def user(self, request, *args, **kwargs):
        user_id = request.query_params.get("user_id")
        if not user_id:
            return Response({"error": "user_id is required"}, status=400)

        try:
            user = User.objects.get(uuid=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        try:
            query_tab_state = self.get_queryset().get(created_by=user, team_id=self.team_id)
            return Response(self.get_serializer(query_tab_state).data)
        except QueryTabState.DoesNotExist:
            return Response({"error": "Query tab state not found"}, status=404)
