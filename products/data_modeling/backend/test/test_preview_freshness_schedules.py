from datetime import timedelta
from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType

M15 = timedelta(minutes=15)
H6 = timedelta(hours=6)


def _no_existing_schedules():
    async def fake_list_schedules(*_args, **_kwargs):
        async def gen():
            return
            yield  # pragma: no cover — empty async generator

        return gen()

    temporal = mock.Mock()
    temporal.list_schedules = fake_list_schedules
    return temporal


def _table_node(team, dag, name, properties):
    return Node.objects.create(team=team, dag=dag, name=name, type=NodeType.TABLE, properties=properties)


def _saved_query_node(team, dag, name, node_type):
    saved_query = DataWarehouseSavedQuery.objects.create(
        name=name, team=team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
    )
    return Node.objects.create(team=team, dag=dag, saved_query=saved_query, type=node_type)


@pytest.mark.django_db
class TestPreviewFreshnessSchedules(BaseTest):
    def test_previews_tiers_without_touching_any_schedule(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)
        Edge.objects.create(team=self.team, dag=dag, source=matview, target=endpoint)
        set_declared_target(endpoint, M15)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                return
                yield  # pragma: no cover — empty async generator

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        out = StringIO()
        with (
            mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{module}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{module}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{module}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            call_command("preview_freshness_schedules", "--team-id", str(self.team.pk), stdout=out)

        # dry-run must not create, update, or delete any schedule
        create.assert_not_called()
        update.assert_not_called()
        delete.assert_not_called()

        output = out.getvalue()
        self.assertIn("tiers: 15min", output)
        self.assertIn("plan: CREATE 1", output)
        self.assertIn("dry run", output)

    def test_seed_mode_models_go_live_from_current_cadence(self):
        # a DAG on a 6h cadence with no per-node targets: raw would schedule nothing, --seed
        # reproduces today's 6h cadence as a tier so go-live doesn't unschedule it.
        dag = DAG.objects.create(team=self.team, name="on-6h", sync_frequency_interval=H6)
        _saved_query_node(self.team, dag, "v", NodeType.VIEW)

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        out = StringIO()
        with (
            mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=_no_existing_schedules())),
            mock.patch(f"{module}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{module}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            call_command(
                "preview_freshness_schedules",
                "--team-id",
                str(self.team.pk),
                "--dag-id",
                str(dag.id),
                "--seed",
                stdout=out,
            )

        create.assert_not_called()
        delete.assert_not_called()
        output = out.getvalue()
        self.assertIn("[seeded]", output)
        self.assertIn("plan: CREATE 1", output)
        self.assertIn("6hour", output)

    def test_flags_unsupported_tier_and_invalid_declared_target(self):
        # go-live audit: a 45min legacy cadence (seeded) must be flagged as unschedulable, and a
        # declared target drifted above its descendant's demand must be flagged as invalid
        dag = DAG.objects.create(team=self.team, name="odd-cadence", sync_frequency_interval=timedelta(minutes=45))
        _saved_query_node(self.team, dag, "legacy_view", NodeType.VIEW)
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=matview, target=endpoint)
        set_declared_target(matview, H6)
        set_declared_target(endpoint, M15)

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        out = StringIO()
        with mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=_no_existing_schedules())):
            call_command(
                "preview_freshness_schedules",
                "--team-id",
                str(self.team.pk),
                "--dag-id",
                str(dag.id),
                "--seed",
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("unsupported tier: 0:45:00", output)
        self.assertIn("invalid declared target: mv", output)

    def test_verbose_flag_gates_per_node_detail(self):
        # the per-node cadence wall is what floods the terminal; it must be verbose-only
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        set_declared_target(endpoint, M15)

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        summary, verbose = StringIO(), StringIO()
        with mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=_no_existing_schedules())):
            call_command("preview_freshness_schedules", "--team-id", str(self.team.pk), stdout=summary)
            call_command("preview_freshness_schedules", "--team-id", str(self.team.pk), "--verbose", stdout=verbose)

        self.assertNotIn("Effective cadences", summary.getvalue())
        self.assertIn("Effective cadences", verbose.getvalue())
        self.assertIn("0:15:00", verbose.getvalue())

    def test_cross_dag_duplication_flags_unsafe_drop(self):
        # one saved query materialized by two DAGs is double-materialized; a query unique to a DAG
        # makes that DAG unsafe to drop, one whose queries all live elsewhere is safe
        shared = DataWarehouseSavedQuery.objects.create(
            name="shared_mv", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        default_dag = DAG.objects.create(team=self.team, name="Default")
        canonical_dag = DAG.objects.create(team=self.team, name="posthog_team")
        Node.objects.create(team=self.team, dag=default_dag, saved_query=shared, type=NodeType.MAT_VIEW)
        Node.objects.create(team=self.team, dag=canonical_dag, saved_query=shared, type=NodeType.MAT_VIEW)
        _saved_query_node(self.team, default_dag, "only_in_default", NodeType.MAT_VIEW)

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        out = StringIO()
        with mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=_no_existing_schedules())):
            call_command("preview_freshness_schedules", "--team-id", str(self.team.pk), stdout=out)

        output = out.getvalue()
        self.assertIn("in >1 DAG (double-materialized): 1", output)
        self.assertIn("only in Default (unsafe to drop): 1", output)
        self.assertIn("only in posthog_team (safe to drop): 0", output)
