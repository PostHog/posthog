from datetime import timedelta
from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError

from products.data_modeling.backend.logic.node_frequency import (
    get_declared_anchor,
    set_declared_anchor,
    set_declared_target,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.test.helpers import (
    saved_query_node as _saved_query_node,
    table_node as _table_node,
)

COMMAND = "products.data_modeling.backend.management.commands.set_schedule_anchor"

M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)
WEEKLY = timedelta(days=7)


@pytest.mark.django_db
class TestSetScheduleAnchor(BaseTest):
    def setUp(self):
        super().setUp()
        self.dag = DAG.get_or_create_default(self.team)
        self.source = _table_node(self.team, self.dag, "events", {"origin": "posthog"})
        self.matview = _saved_query_node(self.team, self.dag, "mv", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=self.dag, source=self.source, target=self.matview)
        set_declared_target(self.matview, H1)

    def _run(self, *args, reconcile_applied=True):
        out = StringIO()
        with (
            mock.patch(f"{COMMAND}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{COMMAND}.reconcile_dag_schedules", return_value=reconcile_applied) as reconcile,
        ):
            call_command("set_schedule_anchor", "--team-id", str(self.team.pk), *args, stdout=out)
        return out.getvalue(), reconcile

    def test_dag_mode_writes_anchor_and_reconciles(self):
        output, reconcile = self._run("--dag-id", str(self.dag.id), "--at", "00:00")
        self.matview.refresh_from_db()
        self.assertEqual(get_declared_anchor(self.matview), 0)
        reconcile.assert_called_once_with(self.dag, require_tiered=True)
        self.assertIn("1hour@00:00", output)

    def test_saved_query_mode_anchors_only_the_named_query(self):
        other = _saved_query_node(self.team, self.dag, "other", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=self.dag, source=self.source, target=other)
        set_declared_target(other, H1)
        self._run("--saved-query-names", "mv", "--at", "02:30")
        self.matview.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(get_declared_anchor(self.matview), 150)
        self.assertIsNone(get_declared_anchor(other))

    def test_dry_run_writes_nothing_but_shows_resulting_tiers(self):
        output, reconcile = self._run("--dag-id", str(self.dag.id), "--at", "00:00", "--dry-run")
        self.matview.refresh_from_db()
        self.assertIsNone(get_declared_anchor(self.matview))
        reconcile.assert_not_called()
        self.assertIn("1hour@00:00", output)

    def test_clear_removes_anchor(self):
        set_declared_anchor(self.matview, 120)
        output, _reconcile = self._run("--dag-id", str(self.dag.id), "--clear")
        self.matview.refresh_from_db()
        self.assertIsNone(get_declared_anchor(self.matview))
        # a clear reported as "anchored" reads as the opposite operation in operator logs
        self.assertIn("cleared 1 node(s)", output)

    def test_on_sets_the_day_component(self):
        self._run("--saved-query-names", "mv", "--at", "02:00", "--on", "tuesday")
        self.matview.refresh_from_db()
        self.assertEqual(get_declared_anchor(self.matview), 1560)

    def test_refuses_weekly_node_without_on(self):
        set_declared_target(self.matview, WEEKLY)
        with self.assertRaisesRegex(CommandError, "weekly cadence"):
            self._run("--dag-id", str(self.dag.id), "--at", "00:00")
        self.matview.refresh_from_db()
        self.assertIsNone(get_declared_anchor(self.matview))

    def test_refuses_upstream_cone_spanning_cadences(self):
        downstream = _saved_query_node(self.team, self.dag, "report", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=self.dag, source=self.matview, target=downstream)
        set_declared_target(self.matview, M15)
        set_declared_target(downstream, H1)
        with self.assertRaisesRegex(CommandError, "spans cadences"):
            self._run("--saved-query-names", "report", "--at", "00:00", "--with-upstream")

    def test_clear_with_upstream_is_allowed_on_a_cone_spanning_cadences(self):
        # a cone anchored while aligned can drift apart later; clearing must stay possible
        downstream = _saved_query_node(self.team, self.dag, "report", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=self.dag, source=self.matview, target=downstream)
        set_declared_target(self.matview, M15)
        set_declared_target(downstream, H1)
        set_declared_anchor(self.matview, 0)
        set_declared_anchor(downstream, 0)
        self._run("--saved-query-names", "report", "--clear", "--with-upstream")
        self.matview.refresh_from_db()
        downstream.refresh_from_db()
        self.assertIsNone(get_declared_anchor(self.matview))
        self.assertIsNone(get_declared_anchor(downstream))

    def test_untiered_dag_stores_anchor_but_says_so_instead_of_claiming_reconcile(self):
        output, _reconcile = self._run("--dag-id", str(self.dag.id), "--at", "00:00", reconcile_applied=False)
        self.matview.refresh_from_db()
        self.assertEqual(get_declared_anchor(self.matview), 0)
        self.assertIn("not on cadence-tier schedules yet", output)

    def test_a_refusal_on_one_dag_writes_nothing_anywhere(self):
        # a --saved-query-names set spanning two DAGs must validate both before writing to either:
        # the second DAG's weekly refusal must not leave the first already anchored and reconciled
        other_dag = DAG.objects.create(team=self.team, name="Other")
        weekly_node = _saved_query_node(self.team, other_dag, "weekly_mv", NodeType.MAT_VIEW)
        set_declared_target(weekly_node, WEEKLY)

        with self.assertRaisesRegex(CommandError, "weekly cadence"):
            self._run("--saved-query-names", "mv", "weekly_mv", "--at", "00:00")

        self.matview.refresh_from_db()
        weekly_node.refresh_from_db()
        self.assertIsNone(get_declared_anchor(self.matview))
        self.assertIsNone(get_declared_anchor(weekly_node))

    def test_with_upstream_anchors_the_cone_when_cadences_align(self):
        downstream = _saved_query_node(self.team, self.dag, "report", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=self.dag, source=self.matview, target=downstream)
        set_declared_target(downstream, H1)
        self._run("--saved-query-names", "report", "--at", "00:00", "--with-upstream")
        self.matview.refresh_from_db()
        downstream.refresh_from_db()
        self.assertEqual(get_declared_anchor(self.matview), 0)
        self.assertEqual(get_declared_anchor(downstream), 0)

    def test_refuses_team_off_the_tiered_flag(self):
        with mock.patch(f"{COMMAND}.tiered_schedules_enabled", return_value=False):
            with self.assertRaisesRegex(CommandError, "tiered-schedules flag"):
                call_command(
                    "set_schedule_anchor", "--team-id", str(self.team.pk), "--dag-id", str(self.dag.id), "--at", "00:00"
                )

    def test_rejects_malformed_arguments(self):
        for args, message in [
            (["--dag-id", str(self.dag.id), "--saved-query-names", "mv", "--at", "00:00"], "exactly one of --dag-id"),
            (["--dag-id", str(self.dag.id)], "exactly one of --at"),
            (["--dag-id", str(self.dag.id), "--at", "00:00", "--clear"], "exactly one of --at"),
            (["--dag-id", str(self.dag.id), "--at", "24:00"], "HH:MM"),
            (["--dag-id", str(self.dag.id), "--clear", "--on", "monday"], "no effect with --clear"),
        ]:
            with self.assertRaisesRegex(CommandError, message):
                self._run(*args)
