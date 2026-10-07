from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade import api
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition, UpstreamTableRef
from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.logic.saved_query_reads import POSTHOG_TABLE_ORIGIN
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.test.helpers import saved_query_node, table_node


class TestSavedQueryReads(BaseTest):
    @parameterized.expand(
        [
            ("legacy_viewer", False, "viewer"),
            ("legacy_editor", False, "editor"),
            ("most_specific_viewer", True, "viewer"),
            ("most_specific_editor", True, "editor"),
        ]
    )
    def test_allowed_saved_query_ids_preserves_object_grants(
        self, _name: str, most_specific: bool, required_level: AccessControlLevel
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.uses_most_specific_access_resolution = most_specific
        self.organization.save(update_fields=["available_product_features", "uses_most_specific_access_resolution"])
        member = self._create_user("member@example.com")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")
        readable = DataWarehouseSavedQuery.objects.create(team=self.team, name="readable")
        editable = DataWarehouseSavedQuery.objects.create(team=self.team, name="editable")
        ungranted = DataWarehouseSavedQuery.objects.create(team=self.team, name="ungranted")
        owned = DataWarehouseSavedQuery.objects.create(team=self.team, name="owned", created_by=member)
        DataWarehouseSavedQuery.objects.create(team=self.team, name="deleted", deleted=True, created_by=member)
        other_team = Team.objects.create(organization=self.organization, name="other")
        DataWarehouseSavedQuery.objects.create(team=other_team, name="other", created_by=member)
        for saved_query, level in [(readable, "viewer"), (editable, "editor")]:
            AccessControl.objects.create(
                team=self.team,
                resource="warehouse_view",
                resource_id=str(saved_query.id),
                organization_member=membership,
                access_level=level,
            )

        access = UserAccessControl(member, team=self.team)
        expected = frozenset({editable.id, owned.id} | ({readable.id} if required_level == "viewer" else set()))
        assert api.allowed_saved_query_ids(self.team.id, access, required_level=required_level) == expected
        with self.assertNumQueries(0):
            assert api.allowed_saved_query_ids(self.team.id, access, required_level=required_level) == expected

        narrowed = api.allowed_saved_query_ids(
            self.team.id, access, required_level=required_level, ids=[owned.id, ungranted.id]
        )
        assert narrowed == frozenset({owned.id})
        with self.assertNumQueries(0):
            assert (
                api.allowed_saved_query_ids(self.team.id, access, required_level=required_level, ids=[]) == frozenset()
            )

        membership.level = OrganizationMembership.Level.ADMIN
        membership.save(update_fields=["level"])
        admin = UserAccessControl(member, team=self.team)
        assert api.allowed_saved_query_ids(self.team.id, admin, required_level=required_level) == frozenset(
            {readable.id, editable.id, ungranted.id, owned.id}
        )

    def test_saved_query_definitions_lists_live_views_with_their_node_interval(self) -> None:
        live = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="orders",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            is_materialized=True,
        )
        node = Node.objects.create(
            team=self.team,
            dag=DAG.objects.create(team=self.team, name="Default"),
            saved_query=live,
            type=NodeType.MAT_VIEW,
        )
        set_declared_target(node, timedelta(hours=6))
        node.save()
        DataWarehouseSavedQuery.objects.create(team=self.team, name="gone", deleted=True)
        other_team = Team.objects.create(organization=self.organization)
        DataWarehouseSavedQuery.objects.create(team=other_team, name="elsewhere")

        assert api.saved_query_definitions(self.team.id) == [
            SavedQueryDefinition(
                id=live.id,
                name="orders",
                hogql="SELECT 1",
                is_materialized=True,
                sync_frequency_interval=timedelta(hours=6),
                is_test=False,
                is_managed=False,
                origin=None,
                created_at=live.created_at,
            )
        ]

    def test_dependent_saved_query_ids_follows_every_node_of_the_source(self) -> None:
        source = DataWarehouseSavedQuery.objects.create(team=self.team, name="source")
        near = DataWarehouseSavedQuery.objects.create(team=self.team, name="near")
        far = DataWarehouseSavedQuery.objects.create(team=self.team, name="far")
        gone = DataWarehouseSavedQuery.objects.create(team=self.team, name="gone", deleted=True)
        first_dag = DAG.objects.create(team=self.team, name="Default")
        second_dag = DAG.objects.create(team=self.team, name="Other")
        source_in_first = Node.objects.create(
            team=self.team, dag=first_dag, name="source", saved_query=source, type=NodeType.VIEW
        )
        source_in_second = Node.objects.create(
            team=self.team, dag=second_dag, name="source", saved_query=source, type=NodeType.VIEW
        )
        for dag, node_source, saved_query in [
            (first_dag, source_in_first, near),
            (second_dag, source_in_second, far),
            (first_dag, source_in_first, gone),
        ]:
            target = Node.objects.create(
                team=self.team, dag=dag, name=saved_query.name, saved_query=saved_query, type=NodeType.VIEW
            )
            Edge.objects.create(team=self.team, dag=dag, source=node_source, target=target)

        assert api.dependent_saved_query_ids(self.team.id, [source.id, near.id]) == {
            source.id: frozenset({near.id, far.id}),
            near.id: frozenset(),
        }

    def test_upstream_table_refs_walks_through_views_and_other_dags_to_tables_only(self) -> None:
        dag = DAG.objects.create(team=self.team, name="Default")
        other_dag = DAG.objects.create(team=self.team, name="Finance")
        invoices = table_node(self.team, other_dag, "invoices", {"origin": POSTHOG_TABLE_ORIGIN})
        revenue = saved_query_node(self.team, other_dag, "revenue", NodeType.VIEW)
        Edge.objects.create(team=self.team, dag=other_dag, source=invoices, target=revenue)
        warehouse_table_id = str(uuid4())
        charges = table_node(
            self.team, dag, "stripe_charges", {"origin": "warehouse", "warehouse_table_id": warehouse_table_id}
        )
        events = table_node(self.team, dag, "events", {"origin": POSTHOG_TABLE_ORIGIN})
        proxy = table_node(
            self.team, dag, "revenue", {"origin": "cross_dag_view", "saved_query_id": str(revenue.saved_query_id)}
        )
        persons = table_node(self.team, dag, "persons", {"origin": POSTHOG_TABLE_ORIGIN})
        middle = saved_query_node(self.team, dag, "middle", NodeType.VIEW)
        target = saved_query_node(self.team, dag, "target", NodeType.VIEW)
        downstream = saved_query_node(self.team, dag, "downstream", NodeType.VIEW)
        for source, dependent in [
            (charges, middle),
            (events, middle),
            (proxy, middle),
            (middle, target),
            (target, downstream),
            (persons, downstream),
        ]:
            Edge.objects.create(team=self.team, dag=dag, source=source, target=dependent)

        assert api.upstream_table_refs(self.team.id, target.saved_query_id) == frozenset(
            {
                UpstreamTableRef(name="stripe_charges", warehouse_table_id=warehouse_table_id),
                UpstreamTableRef(name="events"),
                UpstreamTableRef(name="invoices"),
            }
        )
