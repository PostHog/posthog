import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.warehouse.models import ManagedViewSet

logger = structlog.get_logger(__name__)


class ManagedViewSetSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=True)


class ManagedViewSetViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    lookup_field = "kind"
    lookup_url_kwarg = "kind"

    def list(self, request: Request, *args, **kwargs) -> Response:
        """
        Get all views associated with managed viewsets.
        GET /api/environments/{team_id}/managed_viewsets/
        """
        from posthog.warehouse.models import DataWarehouseSavedQuery

        managed_viewsets = ManagedViewSet.objects.filter(team_id=self.team_id)

        views = (
            DataWarehouseSavedQuery.objects.filter(
                team_id=self.team_id,
                managed_viewset__in=managed_viewsets,
            )
            .exclude(deleted=True)
            .values("id", "name", "created_at", "created_by_id", "managed_viewset__kind")
        )

        return Response({"views": list(views), "count": len(views)}, status=status.HTTP_200_OK)

    def retrieve(self, request: Request, kind: str, *args, **kwargs) -> Response:
        """
        Get all views associated with a specific managed viewset.
        GET /api/environments/{team_id}/managed_viewsets/{kind}/
        """
        from posthog.warehouse.models import DataWarehouseSavedQuery

        if kind not in dict(ManagedViewSet.Kind.choices):
            return Response(
                {"detail": f"Invalid kind. Must be one of: {', '.join(dict(ManagedViewSet.Kind.choices).keys())}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            managed_viewset = ManagedViewSet.objects.get(
                team_id=self.team_id,
                kind=kind,
            )

            views = (
                DataWarehouseSavedQuery.objects.filter(
                    team_id=self.team_id,
                    managed_viewset=managed_viewset,
                )
                .exclude(deleted=True)
                .values("id", "name", "created_at", "created_by_id")
            )

            return Response({"views": list(views), "count": len(views)}, status=status.HTTP_200_OK)

        except ManagedViewSet.DoesNotExist:
            return Response({"views": [], "count": 0}, status=status.HTTP_200_OK)

    def update(self, request: Request, kind: str, *args, **kwargs) -> Response:
        """
        Enable or disable a managed viewset by kind.
        PUT /api/environments/{team_id}/managed_viewsets/{kind}/ with body {"enabled": true/false}
        """
        if kind not in dict(ManagedViewSet.Kind.choices):
            return Response(
                {"detail": f"Invalid kind. Must be one of: {', '.join(dict(ManagedViewSet.Kind.choices).keys())}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ManagedViewSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        enabled = serializer.validated_data["enabled"]

        if enabled:
            managed_viewset, created = ManagedViewSet.objects.get_or_create(
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
                managed_viewset = ManagedViewSet.objects.get(
                    team_id=self.team_id,
                    kind=kind,
                )
                managed_viewset.delete_with_views()

            except ManagedViewSet.DoesNotExist:
                logger.info(
                    "managed_viewset_already_disabled",
                    team_id=self.team_id,
                    kind=kind,
                )

            return Response({"enabled": False, "kind": kind}, status=status.HTTP_200_OK)
