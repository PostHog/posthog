from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import ColumnConfiguration


class ColumnConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ColumnConfiguration
        fields = ["id", "context_key", "columns", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ColumnConfigurationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ColumnConfiguration.objects.all()
    serializer_class = ColumnConfigurationSerializer

    def safely_get_queryset(self, queryset):
        context_key = self.request.GET.get("context_key")
        if context_key:
            queryset = queryset.filter(context_key=context_key)
        return queryset

    def create(self, request, *args, **kwargs):
        """POST to create column configuration for a context_key. Returns 409 if already exists."""
        context_key = request.data.get("context_key")
        columns = request.data.get("columns")

        if not context_key:
            return Response({"error": "context_key is required"}, status=400)

        if columns is None:
            return Response({"error": "columns is required"}, status=400)

        if not isinstance(columns, list):
            return Response({"error": "columns must be a list"}, status=400)

        if len(columns) == 0:
            return Response({"error": "columns cannot be empty"}, status=400)

        if not all(isinstance(col, str) for col in columns):
            return Response({"error": "all columns must be strings"}, status=400)

        if len(columns) > 100:
            return Response({"error": "cannot configure more than 100 columns"}, status=400)

        if ColumnConfiguration.objects.filter(team=self.team, context_key=context_key).exists():
            return Response(
                {"error": "column configuration for this context_key already exists, use PATCH to update"},
                status=409,
            )

        config = ColumnConfiguration.objects.create(
            team=self.team,
            context_key=context_key,
            columns=columns,
        )

        serializer = self.get_serializer(config)
        return Response(serializer.data, status=201)
