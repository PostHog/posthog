import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

logger = structlog.get_logger(__name__)


class DataWarehouseManagedViewSetSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=True, help_text="Whether the managed viewset should exist.")


class DataWarehouseManagedViewSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Saved query the managed viewset owns.")
    name = serializers.CharField(help_text="Name of the saved query.")
    created_at = serializers.DateTimeField(help_text="When the saved query was created.")
    created_by_id = serializers.IntegerField(
        allow_null=True, help_text="User who created the saved query, or null when the sync did."
    )


class DataWarehouseManagedViewSetResponseSerializer(serializers.Serializer):
    views = DataWarehouseManagedViewSerializer(many=True, help_text="Saved queries in the managed viewset.")
    count = serializers.IntegerField(help_text="Number of saved queries returned.")


class DataWarehouseManagedViewSetUpdateResponseSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(help_text="State the managed viewset is now in.")
    kind = serializers.ChoiceField(
        choices=DataWarehouseManagedViewSetKind.choices, help_text="Managed viewset that was toggled."
    )


class DataWarehouseManagedViewSetViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # warehouse_view inherits from warehouse_objects; `update` (enable/disable) creates or
    # deletes saved queries project-wide, so it must require warehouse editor rights.
    scope_object = "warehouse_view"
    serializer_class = _FallbackSerializer
    lookup_field = "kind"
    lookup_url_kwarg = "kind"
    queryset = DataWarehouseManagedViewSet.objects.all()

    @extend_schema(
        responses={
            200: DataWarehouseManagedViewSetResponseSerializer,
            400: OpenApiResponse(description="Unknown managed viewset kind."),
        }
    )
    def retrieve(self, _request: Request, kind: str, *args, **kwargs) -> Response:
        """
        Get all views associated with a specific managed viewset.
        GET /api/environments/{team_id}/managed_viewsets/{kind}/
        """

        if kind not in dict(DataWarehouseManagedViewSetKind.choices):
            return Response(
                {
                    "detail": f"Invalid kind. Must be one of: {', '.join(dict(DataWarehouseManagedViewSetKind.choices).keys())}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            managed_viewset = self.queryset.get(
                team_id=self.team_id,
                kind=kind,
            )

            views = managed_viewset.saved_queries.exclude(deleted=True).values(
                "id", "name", "created_at", "created_by_id"
            )

            return Response({"views": list(views), "count": len(views)}, status=status.HTTP_200_OK)

        except DataWarehouseManagedViewSet.DoesNotExist:
            return Response({"views": [], "count": 0}, status=status.HTTP_200_OK)

    @extend_schema(
        request=DataWarehouseManagedViewSetSerializer,
        responses={
            200: DataWarehouseManagedViewSetUpdateResponseSerializer,
            400: OpenApiResponse(description="Unknown managed viewset kind."),
        },
    )
    def update(self, request: Request, kind: str, *args, **kwargs) -> Response:
        """
        Enable or disable a managed viewset by kind.
        PUT /api/environments/{team_id}/managed_viewsets/{kind}/ with body {"enabled": true/false}
        """
        if kind not in dict(DataWarehouseManagedViewSetKind.choices):
            return Response(
                {
                    "detail": f"Invalid kind. Must be one of: {', '.join(dict(DataWarehouseManagedViewSetKind.choices).keys())}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DataWarehouseManagedViewSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        enabled = serializer.validated_data["enabled"]

        if enabled:
            managed_viewset, created = DataWarehouseManagedViewSet.objects.get_or_create(
                team_id=self.team_id,
                kind=kind,
            )

            if created:
                logger.info(
                    "managed_viewset_enabled",
                    team_id=self.team_id,
                    kind=kind,
                )
            else:
                logger.info(
                    "managed_viewset_resynced",
                    team_id=self.team_id,
                    kind=kind,
                )

            managed_viewset.sync_views()

            return Response({"enabled": True, "kind": kind}, status=status.HTTP_200_OK)
        else:
            try:
                managed_viewset = DataWarehouseManagedViewSet.objects.get(
                    team_id=self.team_id,
                    kind=kind,
                )
                managed_viewset.delete_with_views()

            except DataWarehouseManagedViewSet.DoesNotExist:
                logger.info(
                    "managed_viewset_already_disabled",
                    team_id=self.team_id,
                    kind=kind,
                )

            return Response({"enabled": False, "kind": kind}, status=status.HTTP_200_OK)
