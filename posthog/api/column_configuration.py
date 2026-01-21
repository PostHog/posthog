from django.db import IntegrityError, models

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict
from posthog.models import ColumnConfiguration


class ColumnConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ColumnConfiguration
        fields = [
            "id",
            "context_key",
            "columns",
            "name",
            "filters",
            "visibility",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "team"]


@extend_schema(tags=[ProductKey.PRODUCT_ANALYTICS])
class ColumnConfigurationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ColumnConfiguration.objects.all()
    serializer_class = ColumnConfigurationSerializer

    def safely_get_queryset(self, queryset):
        # TODO: Review this to ensure users only access their own views or shared views
        context_key = self.request.GET.get("context_key")
        if context_key:
            # Get named views (user's own private + all shared) and legacy unnamed config
            queryset = queryset.filter(
                models.Q(context_key=context_key)
                & (
                    models.Q(name__isnull=False, visibility="private", created_by=self.request.user)
                    | models.Q(name__isnull=False, visibility="shared")
                    | models.Q(name__isnull=True)  # Legacy unnamed config
                )
            )
        return queryset.order_by("visibility", "-created_at")

    def perform_create(self, serializer):
        try:
            serializer.save(team=self.team, created_by=self.request.user)
        except IntegrityError as e:
            error_str = str(e)
            if "unique_user_view_name" in error_str:
                raise Conflict(detail="A private view with this name already exists")
            elif "unique_team_view_name" in error_str:
                raise Conflict(detail="A shared view with this name already exists")
            raise

    def create(self, request, *args, **kwargs):
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

        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        # Check permissions
        if not (instance.created_by == request.user or instance.visibility == "shared"):
            return Response({"error": "You don't have permission to edit this view"}, status=403)

        # Log the change for version control
        try:
            from posthog.models.activity_logging.activity_log import log_activity

            # TODO: Review this, I think this is entirely wrong.
            log_activity(
                team_id=self.team_id,
                user=request.user,
                item_type="column_configuration",
                item_id=str(instance.id),
                activity="updated",
                detail={"name": instance.name, "changes": dict(request.data)},
            )
        except Exception:
            # Don't fail the update if logging fails
            # TODO: Log the error
            pass

        return super().update(request, *args, **kwargs)
