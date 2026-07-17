from typing import Any

from django.db import IntegrityError
from django.db.models import Q, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import log_activity_from_viewset
from posthog.exceptions import Conflict
from posthog.models import ColumnConfiguration


class ColumnConfigurationSerializer(serializers.ModelSerializer):
    filters = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Column filter state persisted with this view configuration.",
    )
    order_by = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        allow_empty=True,
        help_text="Ordered list of HogQL expressions describing the table sort. Null preserves the current sort on apply (legacy rows); an empty list explicitly means no sort.",
    )
    properties = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Product-specific view state that does not fit the columnar fields (e.g. Customer analytics overview tiles and column display).",
    )

    class Meta:
        model = ColumnConfiguration
        fields = [
            "id",
            "context_key",
            "columns",
            "name",
            "filters",
            "order_by",
            "properties",
            "visibility",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "team"]

    def validate_filters(self, filters):
        if not filters:
            return []
        return filters

    def validate_properties(self, properties):
        # create() validates this inline for a uniform error envelope, but that gate
        # doesn't run on partial updates — guard PATCH here so a non-dict can't be stored.
        if properties is not None and not isinstance(properties, dict):
            raise serializers.ValidationError("properties must be an object")
        return properties

    def to_representation(self, instance: ColumnConfiguration):
        values = super().to_representation(instance)
        values["filters"] = self.validate_filters(values["filters"])
        return values


@extend_schema(extensions={"x-product": ProductKey.PRODUCT_ANALYTICS})
class ColumnConfigurationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ColumnConfiguration.objects.all()
    serializer_class = ColumnConfigurationSerializer

    def safely_get_queryset(self, queryset):
        # Always visibility-scope (own private + team shared) so a request without a
        # context_key — or an object lookup by id — can't reach another user's private view.
        queryset = queryset.filter(Q(visibility="private", created_by=self.request.user) | Q(visibility="shared"))
        context_key = self.request.GET.get("context_key")
        if context_key:
            queryset = queryset.filter(context_key=context_key)
        return queryset.order_by("visibility", "-created_at")

    def safely_get_object(self, queryset: QuerySet) -> Any:
        try:
            object = queryset.get(pk=self.kwargs["pk"])
        except ColumnConfiguration.DoesNotExist:
            # The queryset is visibility-scoped, so a row outside it (another user's private
            # view, or a wrong id) is a 404 — not an unhandled 500.
            raise NotFound("View not found")

        if self.request.method not in SAFE_METHODS and object.created_by != self.request.user:
            raise PermissionDenied("You do not have permission to change this view")

        return object

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

        order_by = request.data.get("order_by")
        if order_by is not None:
            if not isinstance(order_by, list):
                return Response({"error": "order_by must be a list"}, status=400)

            if not all(isinstance(item, str) for item in order_by):
                return Response({"error": "all order_by entries must be strings"}, status=400)

            if len(order_by) > 100:
                return Response({"error": "cannot order by more than 100 expressions"}, status=400)

        properties = request.data.get("properties")
        if properties is not None and not isinstance(properties, dict):
            return Response({"error": "properties must be an object"}, status=400)

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        try:
            instance = serializer.save(team=self.team, created_by=self.request.user)
            self._log_activity(instance=instance, previous=None)
        except IntegrityError as e:
            error_str = str(e)
            if "unique_user_view_name" in error_str:
                raise Conflict(detail="A private view with this name already exists")
            elif "unique_team_view_name" in error_str:
                raise Conflict(detail="A shared view with this name already exists")
            raise

    def perform_update(self, serializer):
        previous = self.get_object()
        instance = serializer.save()
        self._log_activity(instance=instance, previous=previous)

    def _log_activity(self, instance, previous):
        log_activity_from_viewset(
            self,
            instance=instance,
            previous=previous,
            name=f"{instance.context_key.split(':')[0].replace('-', ' ').capitalize()} column configuration",
        )
