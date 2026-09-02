from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization, Team

from products.data_modeling.backend.logic.cohort_scheduling import Tier
from products.data_modeling.backend.logic.tier_membership import EPHEMERAL_SKIPPED, SCHEDULED, LiveTier, classify_node
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType

TEMPORAL_READ = "products.data_modeling.backend.management.commands.check_node_tier_schedule.Command._read_live_tiers"


class TestClassifyNodeEphemeral(SimpleTestCase):
    def _tier(self, node_id: str, seconds: int = 900) -> LiveTier:
        return LiveTier(
            schedule_id=f"dag:{seconds}",
            interval_seconds=seconds,
            covers_whole_dag=False,
            node_ids=frozenset({node_id}),
        )

    def _classify(self, *, node_type: str, has_backing_table: bool) -> str:
        return classify_node(
            node_id="n1",
            name="rep_sales_events",
            node_type=node_type,
            dag_id="d1",
            dag_name="Default",
            live_tiers=[self._tier("n1")],
            expected_tier=Tier(timedelta(seconds=900)),
            has_backing_table=has_backing_table,
        ).verdict

    def test_view_node_over_a_live_table_is_not_reported_as_scheduled(self):
        # It sits in exactly the tier reconcile wants, so every tier comparison says "scheduled" —
        # but execute_dag classes a view node ephemeral and skips it, so it never materializes.
        assert self._classify(node_type=NodeType.VIEW, has_backing_table=True) == EPHEMERAL_SKIPPED

    @parameterized.expand(
        [
            # a view with no table is a real ephemeral view, working as intended
            ("ephemeral_view_without_table", NodeType.VIEW, False),
            ("matview_with_table", NodeType.MAT_VIEW, True),
        ]
    )
    def test_healthy_nodes_stay_scheduled(self, _name, node_type, has_backing_table):
        assert self._classify(node_type=node_type, has_backing_table=has_backing_table) == SCHEDULED


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
