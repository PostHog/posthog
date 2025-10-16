import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.warehouse.models import DataWarehouseManagedViewSet

logger = structlog.get_logger(__name__)


class DataWarehouseManagedViewSetSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=True)


class DataWarehouseManagedViewSetViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    lookup_field = "kind"
    lookup_url_kwarg = "kind"
    queryset = DataWarehouseManagedViewSet.objects.all()

    def retrieve(self, _request: Request, kind: str, *args, **kwargs) -> Response:
        """
        Get all views associated with a specific managed viewset.
        GET /api/environments/{team_id}/managed_viewsets/{kind}/
        """

        if kind not in dict(DataWarehouseManagedViewSet.Kind.choices):
            return Response(
                {
                    "detail": f"Invalid kind. Must be one of: {', '.join(dict(DataWarehouseManagedViewSet.Kind.choices).keys())}"
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

    def update(self, request: Request, kind: str, *args, **kwargs) -> Response:
        """
        Enable or disable a managed viewset by kind.
        PUT /api/environments/{team_id}/managed_viewsets/{kind}/ with body {"enabled": true/false}
        """
        if kind not in dict(DataWarehouseManagedViewSet.Kind.choices):
            return Response(
                {
                    "detail": f"Invalid kind. Must be one of: {', '.join(dict(DataWarehouseManagedViewSet.Kind.choices).keys())}"
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
