from posthog.test.base import BaseTest
from posthog.warehouse.models import WarehouseCluster, WarehouseClusterTeam, WarehouseNode
from django.db.utils import IntegrityError
from django.core.exceptions import ValidationError


class TestUser(BaseTest):
    def test_team_only_has_one_read_cluster(self):
        cluster = WarehouseCluster.objects.create(organization=self.organization)

        WarehouseClusterTeam.objects.create(team=self.team, cluster=cluster, is_read_cluster=True)
        WarehouseClusterTeam.objects.create(team=self.team, cluster=cluster, is_read_cluster=False)
        with self.assertRaises(IntegrityError):
            WarehouseClusterTeam.objects.create(team=self.team, cluster=cluster, is_read_cluster=True)

    def test_write_node_cannot_be_read_only(self):
        cluster = WarehouseCluster.objects.create(organization=self.organization)
        read_only_node = WarehouseNode.objects.create(host="localhost", cluster=cluster, is_read_only=True)
        cluster.write_node = read_only_node
        with self.assertRaises(ValidationError):
            cluster.save()
