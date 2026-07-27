import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models import Organization, Team

from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType

TEMPORAL_READ = "products.data_modeling.backend.management.commands.check_node_tier_schedule.Command._read_live_tiers"


class TestCheckNodeTierScheduleGuards(BaseTest):
    """The guards that must hold before the command reads live schedules out of Temporal."""

    def _node(self, dag: DAG, name: str) -> Node:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "select 1"}
        )
        return Node.objects.create(team=self.team, dag=dag, name=name, type=NodeType.MAT_VIEW, saved_query=saved_query)

    def test_dag_id_from_another_team_is_refused_before_reading_temporal(self):
        # Schedule ids and per-tier node counts are team data. Resolving --dag-id only for display
        # while still querying Temporal by that id would print another team's live schedules.
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"), name="other")
        foreign_dag = DAG.objects.create(team=other_team, name="Default")

        with patch(TEMPORAL_READ) as read_live:
            with pytest.raises(CommandError, match="do not belong to team"):
                call_command(
                    "check_node_tier_schedule", "--team-id", str(self.team.pk), "--dag-id", str(foreign_dag.id)
                )

        read_live.assert_not_called()

    def test_selector_matching_nothing_errors_instead_of_dumping_the_dag(self):
        # A typo'd --name used to fall through to "no selector given" and dump every node in the DAG,
        # which reads as a clean bill of health for a node that was never actually inspected.
        dag = DAG.objects.create(team=self.team, name="Default")
        self._node(dag, "real_view")

        with patch(TEMPORAL_READ) as read_live:
            with pytest.raises(CommandError, match="matches that selector"):
                call_command(
                    "check_node_tier_schedule",
                    "--team-id",
                    str(self.team.pk),
                    "--name",
                    "typo_view",
                    "--dag-id",
                    str(dag.id),
                )

        read_live.assert_not_called()
