from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from parameterized import parameterized

from products.data_modeling.backend.models import DAG, Edge, Node
from products.data_modeling.backend.models.dag import DEFAULT_DAG_NAME, build_cohort_dag_name
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.services.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_warehouse.backend.models import DataWarehouseSavedQuery


def _patch_temporal(test_method):
    """Wrap a test method with the mocks every migrate-command test needs.

    The command talks to Temporal in three places — sync_connect, create_schedule,
    schedule_exists, delete_schedule. None of those have side effects we want in
    tests, so we replace them with no-op MagicMocks and pass the mocks through to
    the test so it can assert against them.
    """

    @patch("products.data_modeling.backend.management.commands.migrate_teams_to_dag_schedules.delete_schedule")
    @patch("products.data_modeling.backend.management.commands.migrate_teams_to_dag_schedules.create_schedule")
    @patch(
        "products.data_modeling.backend.management.commands.migrate_teams_to_dag_schedules.schedule_exists",
        return_value=False,
    )
    @patch(
        "products.data_modeling.backend.management.commands.migrate_teams_to_dag_schedules.sync_connect",
        return_value=MagicMock(),
    )
    def wrapper(self, *args, **kwargs):
        return test_method(self, *args, **kwargs)

    wrapper.__name__ = test_method.__name__
    return wrapper


@pytest.mark.django_db
class TestMigrateTeamsToDagSchedules(BaseTest):
    def _make_saved_query(self, name: str, sync_frequency_interval: timedelta | None) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=sync_frequency_interval,
        )

    def _seed_node(self, sq: DataWarehouseSavedQuery, dag: DAG) -> Node:
        # sync_saved_query_to_dag would route a freshly-created SQ to its
        # frequency-cohort DAG via our new logic, so for migration tests we
        # need to force everything into a single source DAG (the team's
        # pre-migration Default) and let _migrate_dag split it.
        node, _ = Node.objects.get_or_create(
            team=self.team,
            saved_query=sq,
            dag=dag,
            defaults={"name": sq.name, "type": NodeType.VIEW},
        )
        return node

    def _run(self) -> None:
        call_command("migrate_teams_to_dag_schedules", "--team-ids", str(self.team.pk))

    @_patch_temporal
    def test_skips_dag_with_no_scheduled_nodes(self, _sc, _exists, mock_create, _del):
        DAG.get_or_create_default(self.team)
        self._run()
        mock_create.assert_not_called()

    @_patch_temporal
    def test_single_frequency_creates_single_cohort_dag(self, _sc, _exists, mock_create, _del):
        source_dag = DAG.get_or_create_default(self.team)
        sq = self._make_saved_query("view_a", sync_frequency_interval=timedelta(hours=1))
        self._seed_node(sq, source_dag)

        self._run()

        cohort_dag = DAG.objects.get(team=self.team, name=build_cohort_dag_name(DEFAULT_DAG_NAME, timedelta(hours=1)))
        assert cohort_dag.sync_frequency_interval == timedelta(hours=1)
        assert Node.objects.filter(saved_query=sq).get().dag_id == cohort_dag.id
        mock_create.assert_called_once()
        sq.refresh_from_db()
        assert sq.sync_frequency_interval is None

    @parameterized.expand(
        [
            ("two_freq", [timedelta(hours=1), timedelta(hours=6)]),
            ("three_freq", [timedelta(hours=1), timedelta(hours=6), timedelta(days=1)]),
        ]
    )
    @_patch_temporal
    def test_multi_frequency_splits_into_one_cohort_dag_per_frequency(
        self, _sc, _exists, mock_create, _del, _name, intervals
    ):
        source_dag = DAG.get_or_create_default(self.team)
        sqs_by_interval = {}
        for i, interval in enumerate(intervals):
            sq = self._make_saved_query(f"view_{i}", sync_frequency_interval=interval)
            self._seed_node(sq, source_dag)
            sqs_by_interval[interval] = sq

        self._run()

        for interval, sq in sqs_by_interval.items():
            cohort_name = build_cohort_dag_name(DEFAULT_DAG_NAME, interval)
            cohort_dag = DAG.objects.get(team=self.team, name=cohort_name)
            assert cohort_dag.sync_frequency_interval == interval
            node = Node.objects.get(saved_query=sq)
            assert node.dag_id == cohort_dag.id
            sq.refresh_from_db()
            assert sq.sync_frequency_interval is None
        assert mock_create.call_count == len(intervals)

    @_patch_temporal
    def test_idempotent_rerun_after_intervals_cleared(self, _sc, _exists, mock_create, _del):
        source_dag = DAG.get_or_create_default(self.team)
        sq = self._make_saved_query("view_a", sync_frequency_interval=timedelta(hours=1))
        self._seed_node(sq, source_dag)

        self._run()
        first_call_count = mock_create.call_count
        # second run: SQ.sync_frequency_interval is now None so the source DAG
        # has no scheduled nodes; the command should short-circuit and create no
        # additional schedules.
        self._run()
        assert mock_create.call_count == first_call_count

    @_patch_temporal
    def test_cross_cohort_edges_are_dropped(self, _sc, _exists, mock_create, _del):
        source_dag = DAG.get_or_create_default(self.team)
        upstream_sq = DataWarehouseSavedQuery.objects.create(
            name="upstream_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=timedelta(hours=1),
        )
        # downstream references upstream by name, creating a real intra-DAG edge
        downstream_sq = DataWarehouseSavedQuery.objects.create(
            name="downstream_view",
            team=self.team,
            query={"query": "SELECT * FROM upstream_view", "kind": "HogQLQuery"},
            sync_frequency_interval=timedelta(hours=6),
        )
        sync_saved_query_to_dag(upstream_sq, dag=source_dag)
        sync_saved_query_to_dag(downstream_sq, dag=source_dag)
        upstream_node = Node.objects.get(saved_query=upstream_sq)
        downstream_node = Node.objects.get(saved_query=downstream_sq)
        # sanity: edge exists pre-migration
        assert Edge.objects.filter(source=upstream_node, target=downstream_node).exists()

        self._run()

        upstream_node.refresh_from_db()
        downstream_node.refresh_from_db()
        assert upstream_node.dag.name == build_cohort_dag_name(DEFAULT_DAG_NAME, timedelta(hours=1))
        assert downstream_node.dag.name == build_cohort_dag_name(DEFAULT_DAG_NAME, timedelta(hours=6))
        # cross-cohort edge must be gone — orchestrator no longer ties cohorts together
        assert not Edge.objects.filter(source=upstream_node, target=downstream_node).exists()

    @_patch_temporal
    def test_dry_run_makes_no_changes(self, _sc, _exists, mock_create, _del):
        source_dag = DAG.get_or_create_default(self.team)
        sq = self._make_saved_query("view_a", sync_frequency_interval=timedelta(hours=1))
        node = self._seed_node(sq, source_dag)

        call_command("migrate_teams_to_dag_schedules", "--team-ids", str(self.team.pk), "--dry-run")

        node.refresh_from_db()
        assert node.dag_id == source_dag.id
        sq.refresh_from_db()
        assert sq.sync_frequency_interval == timedelta(hours=1)
        mock_create.assert_not_called()
        assert not DAG.objects.filter(
            team=self.team, name=build_cohort_dag_name(DEFAULT_DAG_NAME, timedelta(hours=1))
        ).exists()


@pytest.mark.django_db
class TestSyncSavedQueryToDagFrequencyRouting(BaseTest):
    """Behavior we added to sync_saved_query_to_dag: route by SQ.sync_frequency_interval."""

    def test_unscheduled_saved_query_lands_in_default_dag(self):
        sq = DataWarehouseSavedQuery.objects.create(
            name="unscheduled",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        node = sync_saved_query_to_dag(sq)

        assert node is not None
        assert node.dag.name == DEFAULT_DAG_NAME
        assert node.dag.sync_frequency_interval == timedelta(days=1)  # the DAG model default

    @parameterized.expand(
        [
            (timedelta(minutes=15),),
            (timedelta(hours=1),),
            (timedelta(hours=6),),
            (timedelta(days=1),),
            (timedelta(days=7),),
        ]
    )
    def test_scheduled_saved_query_lands_in_frequency_cohort_dag(self, interval):
        sq = DataWarehouseSavedQuery.objects.create(
            name=f"scheduled_{int(interval.total_seconds())}",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=interval,
        )

        node = sync_saved_query_to_dag(sq)

        assert node is not None
        expected_name = build_cohort_dag_name(DEFAULT_DAG_NAME, interval)
        assert node.dag.name == expected_name
        assert node.dag.sync_frequency_interval == interval

    def test_explicit_dag_argument_overrides_routing(self):
        explicit_dag = DAG.objects.create(team=self.team, name="explicit-target")
        sq = DataWarehouseSavedQuery.objects.create(
            name="ignores_routing",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=timedelta(hours=1),
        )

        node = sync_saved_query_to_dag(sq, dag=explicit_dag)

        assert node is not None
        assert node.dag_id == explicit_dag.id
