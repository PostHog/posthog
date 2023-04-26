from posthog.permissions import OrganizationMemberPermissions
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import WarehouseCluster, WarehouseNode
from posthog.api.shared import UserBasicSerializer
from posthog.api.routing import StructuredViewSetMixin


class NodeSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = WarehouseNode
        fields = [
            "id",
            "host",
            "port",
            "database",
            "is_read_only",
            "created_by",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
        ]


class ClusterSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    nodes = serializers.SerializerMethodField()

    class Meta:
        model = WarehouseCluster
        fields = ["id", "name", "write_node", "created_by", "created_at", "nodes"]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
        ]

    def get_nodes(self, cluster: WarehouseCluster):
        return [NodeSerializer(node).data for node in cluster.warehousenode_set.all()]


class ClusterViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Warehouse Clusters.
    """

    queryset = WarehouseCluster.objects.all()
    serializer_class = ClusterSerializer
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def get_queryset(self):
        return (
            self.filter_queryset_by_parents_lookups(super().get_queryset())
            .select_related("created_by")
            .order_by(self.ordering)
        )
