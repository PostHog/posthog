from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from posthog.models import Product
from posthog.api.routing import StructuredViewSetMixin
from rest_framework import serializers
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "description", "price", "currency", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ProductViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update and delete products.
    """

    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def get_queryset(self):
        return super().get_queryset().filter(team_id=self.team_id)

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id)
