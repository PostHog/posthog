from posthog.test.base import BaseTest
from posthog.warehouse.models import Cluster, ClusterTeam, Node
from django.db.utils import IntegrityError
from django.core.exceptions import ValidationError


class TestUser(BaseTest):
    def test_team_only_has_one_read_cluster(self):
        cluster = Cluster.objects.create(organization=self.organization)

        ClusterTeam.objects.create(team=self.team, cluster=cluster, is_read_cluster=True)
        ClusterTeam.objects.create(team=self.team, cluster=cluster, is_read_cluster=False)
        with self.assertRaises(IntegrityError):
            ClusterTeam.objects.create(team=self.team, cluster=cluster, is_read_cluster=True)

    def test_write_node_cannot_be_read_only(self):
        cluster = Cluster.objects.create(organization=self.organization)
        read_only_node = Node.objects.create(host="localhost", cluster=cluster, is_read_only=True)
        cluster.write_node = read_only_node
        with self.assertRaises(ValidationError):
            cluster.save()
