import importlib
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.database.database import Database

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.data_catalog.backend.logic.lineage import (
    LineageSyncOutcome,
    dependency_names,
    has_executable_definition,
    sync_metric_lineage,
)
from products.data_catalog.backend.logic.metrics import (
    bulk_soft_delete_metrics,
    soft_delete_metric,
    update_metric,
    upsert_metric,
)
from products.data_catalog.backend.models import Metric
from products.data_catalog.backend.tasks.tasks import sync_metric_lineage_task
from products.data_modeling.backend.facade.api import mark_metric_node_degraded
from products.data_modeling.backend.facade.models import DAG, Edge, Node, NodeType

_HOGQL_EVENTS = {"kind": "HogQLQuery", "query": "select count() from events"}
_HOGQL_PERSONS = {"kind": "HogQLQuery", "query": "select count() from persons"}
_HOGQL_SYSTEM = {"kind": "HogQLQuery", "query": "select count() from system.information_schema.metrics"}
_HOGQL_VIEW = {"kind": "HogQLQuery", "query": "select count() from accounts_view"}
_HOGQL_CTE_SHADOWING_A_TABLE = {
    "kind": "HogQLQuery",
    "query": "with events as (select * from persons) select count() from events",
}
_HOGQL_NUMBERS_SPINE = {
    "kind": "HogQLQuery",
    "query": "select count() from numbers(10) join events on 1",
}
_MARKDOWN = {"kind": "MarkdownDefinition", "markdown": "Count the accounts, then divide."}
_TRENDS_EVENTS = {
    "kind": "TrendsQuery",
    "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
}


class TestDependencyNames(BaseTest):
    def _metric(self, definition: dict | None, referenced: list[str] | None = None) -> Metric:
        metric = Metric(team=self.team, name="m", description="d", definition=definition)
        metric.referenced_table_names = referenced or []
        return metric

    @parameterized.expand(
        [
            ("hogql_tables", _HOGQL_EVENTS, ["events"], ["events"]),
            ("system_tables_dropped", _HOGQL_SYSTEM, ["system.information_schema.metrics"], []),
            ("hogql_view_beats_its_resolved_sources", _HOGQL_VIEW, ["events", "persons"], ["accounts_view"]),
            ("hogql_cte_does_not_shadow_a_table", _HOGQL_CTE_SHADOWING_A_TABLE, ["persons"], ["persons"]),
            ("hogql_table_function_is_not_upstream", _HOGQL_NUMBERS_SPINE, ["events"], ["events"]),
            ("events_node_adds_events", _TRENDS_EVENTS, [], ["events"]),
            ("warehouse_series_keeps_both", _TRENDS_EVENTS, ["stripe_charges"], ["events", "stripe_charges"]),
            ("markdown_reads_nothing", _MARKDOWN, [], []),
        ]
    )
    def test_dependency_names(self, _name, definition, referenced, expected) -> None:
        assert dependency_names(self._metric(definition, referenced)) == expected

    @parameterized.expand(
        [
            ("hogql", _HOGQL_EVENTS, True),
            ("markdown", _MARKDOWN, False),
            ("no_definition", None, False),
        ]
    )
    def test_has_executable_definition(self, _name, definition, expected) -> None:
        assert has_executable_definition(self._metric(definition)) is expected


class TestSyncMetricLineage(BaseTest):
    def _upsert(self, name: str, **kwargs) -> Metric:
        return upsert_metric(team=self.team, user=self.user, name=name, description="d", **kwargs)

    def _node(self, metric: Metric) -> Node | None:
        return Node.objects.filter(team=self.team, metric_id=metric.id).first()

    def _sources(self, metric: Metric) -> set[str]:
        node = self._node(metric)
        assert node is not None
        return {edge.source.name for edge in Edge.objects.filter(target=node).select_related("source")}

    def _sync(self, metric: Metric) -> None:
        with team_scope(self.team.id):
            sync_metric_lineage(Metric.objects.for_team(self.team.id).select_related("team").get(pk=metric.pk))

    def test_a_metric_with_a_query_gets_a_node_and_its_edges(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)

        self._sync(metric)

        node = self._node(metric)
        assert node is not None
        assert node.type == NodeType.METRIC
        assert node.name == "mrr"
        assert self._sources(metric) == {"events"}

    def test_a_rename_follows_and_a_new_definition_replaces_the_edges(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)
        self._sync(metric)

        renamed = update_metric(metric, team=self.team, user=self.user, name="revenue", definition=_HOGQL_PERSONS)
        self._sync(renamed)

        node = self._node(renamed)
        assert node is not None
        assert node.name == "revenue"
        assert self._sources(renamed) == {"persons"}

    @parameterized.expand([("markdown", _MARKDOWN), ("cleared", None)])
    def test_a_metric_that_stops_being_executable_loses_its_node(self, _name, definition) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)
        self._sync(metric)

        metric.definition = definition
        metric.save(update_fields=["definition"])
        self._sync(metric)

        assert self._node(metric) is None

    def test_a_failing_sync_leaves_a_marker_instead_of_raising(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)

        with patch(
            "products.data_catalog.backend.logic.lineage.sync_metric_to_dag",
            side_effect=RuntimeError("schema build blew up"),
        ):
            self._sync(metric)

        node = self._node(metric)
        assert node is not None
        assert node.properties["system"]["degraded_sync"]["error"] == "schema build blew up"

    def test_soft_delete_removes_the_node(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)
        self._sync(metric)

        soft_delete_metric(metric, self.user)

        assert self._node(metric) is None

    def test_a_failing_node_delete_does_not_fail_the_metric_delete(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)
        self._sync(metric)

        with patch(
            "products.data_catalog.backend.logic.lineage.delete_metric_node",
            side_effect=RuntimeError("postgres went away"),
        ):
            soft_delete_metric(metric, self.user)

        metric.refresh_from_db()
        assert metric.deleted is True

    def test_bulk_delete_removes_every_node(self) -> None:
        first = self._upsert("mrr", definition=_HOGQL_EVENTS)
        second = self._upsert("arr", definition=_HOGQL_EVENTS)
        self._sync(first)
        self._sync(second)

        bulk_soft_delete_metrics([first, second], self.user)

        assert not Node.objects.filter(team=self.team, type=NodeType.METRIC).exists()

    def test_a_sync_that_lands_after_a_delete_leaves_no_node(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)
        self._sync(metric)
        assert self._node(metric) is not None
        with team_scope(self.team.id):
            in_flight = Metric.objects.for_team(self.team.id).select_related("team").get(pk=metric.pk)

        soft_delete_metric(metric, self.user)
        outcome = sync_metric_lineage(in_flight)

        assert outcome == LineageSyncOutcome.REMOVED
        assert self._node(metric) is None

    def test_a_write_dispatches_the_sync_only_when_it_can_change_the_lineage(self) -> None:
        with patch("products.data_catalog.backend.logic.metrics.sync_metric_lineage_task") as task:
            with self.captureOnCommitCallbacks(execute=True):
                metric = self._upsert("mrr", definition=_HOGQL_EVENTS)

            task.delay.assert_called_once_with(str(metric.id), self.team.id)
            task.delay.reset_mock()

            with self.captureOnCommitCallbacks(execute=True):
                upsert_metric(team=self.team, user=self.user, name="mrr", description="what it counts")

            task.delay.assert_not_called()

    def test_metric_nodes_live_in_the_teams_default_dag(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)

        self._sync(metric)

        node = self._node(metric)
        assert node is not None
        assert node.dag_id == DAG.get_or_create_default(self.team).id


class TestBackfillMetricLineage(BaseTest):
    def _upsert(self, name: str, **kwargs) -> Metric:
        return upsert_metric(team=self.team, user=self.user, name=name, description="d", **kwargs)

    def test_backfill_creates_nodes_and_builds_one_schema_per_team(self) -> None:
        self._upsert("mrr", definition=_HOGQL_EVENTS)
        self._upsert("arr", definition=_HOGQL_EVENTS)
        deleted = self._upsert("gone", definition=_HOGQL_EVENTS)
        soft_delete_metric(deleted, self.user)

        with patch(
            "products.data_catalog.backend.management.commands.backfill_metric_lineage.Database"
        ) as database_class:
            database_class.create_for.return_value = Database.create_for(
                team=self.team, bypass_warehouse_access_control=True
            )
            call_command("backfill_metric_lineage", "--team-id", str(self.team.pk))

        assert database_class.create_for.call_count == 1
        assert Node.objects.filter(team=self.team, type=NodeType.METRIC).count() == 2

    def test_dry_run_writes_nothing(self) -> None:
        self._upsert("mrr", definition=_HOGQL_EVENTS)

        call_command("backfill_metric_lineage", "--team-id", str(self.team.pk), "--dry-run")

        assert not Node.objects.filter(team=self.team, type=NodeType.METRIC).exists()

    def test_backfill_drops_a_node_whose_metric_is_gone(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)
        with team_scope(self.team.id):
            sync_metric_lineage(Metric.objects.for_team(self.team.id).select_related("team").get(pk=metric.pk))
        # A delete whose node removal failed leaves exactly this: a node with no live metric.
        Metric.objects.for_team(self.team.id).filter(pk=metric.pk).update(deleted=True)

        call_command("backfill_metric_lineage", "--team-id", str(self.team.pk))

        assert not Node.objects.filter(team=self.team, type=NodeType.METRIC).exists()

    @parameterized.expand(
        [
            ("a_failed_sync", {"side_effect": RuntimeError("schema build blew up")}, "1 degraded"),
            ("a_missing_dependency_node", {"return_value": ["accounts_view"]}, "1 unresolved"),
        ]
    )
    def test_backfill_reports_what_the_sync_reported_not_a_success(self, _name, patched, expected) -> None:
        self._upsert("mrr", definition=_HOGQL_EVENTS)
        output = StringIO()

        with patch("products.data_catalog.backend.logic.lineage.sync_metric_to_dag", **patched):
            call_command("backfill_metric_lineage", "--team-id", str(self.team.pk), stdout=output)

        assert expected in output.getvalue()
        assert "0 synced" in output.getvalue()

    def _child_environment(self) -> Team:
        return Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="staging"
        )

    def _patched_database(self):
        patcher = patch("products.data_catalog.backend.management.commands.backfill_metric_lineage.Database")
        database_class = patcher.start()
        self.addCleanup(patcher.stop)
        database_class.create_for.return_value = Database.create_for(
            team=self.team, bypass_warehouse_access_control=True
        )
        return database_class

    def test_a_team_whose_schema_fails_does_not_end_the_run(self) -> None:
        self._upsert("mrr", definition=_HOGQL_EVENTS)
        later_team = Team.objects.create(organization=self.organization, name="second project")
        later_metric = upsert_metric(
            team=later_team, user=self.user, name="arr", description="d", definition=_HOGQL_EVENTS
        )
        output = StringIO()
        database_class = self._patched_database()
        schema = database_class.create_for.return_value

        def build_schema(**kwargs) -> Database:
            if kwargs["team"].pk == self.team.pk:
                raise RuntimeError("schema build blew up")
            return schema

        database_class.create_for.side_effect = build_schema

        call_command("backfill_metric_lineage", stdout=output)

        assert "1 team(s) failed" in output.getvalue()
        assert Node.objects.filter(team=later_team, metric_id=later_metric.id).exists()

    def test_a_child_environment_does_not_repeat_its_projects_backfill(self) -> None:
        self._upsert("mrr", definition=_HOGQL_EVENTS)
        self._child_environment()
        database_class = self._patched_database()

        call_command("backfill_metric_lineage")

        assert database_class.create_for.call_count == 1
        assert Node.objects.filter(type=NodeType.METRIC).count() == 1

    def test_a_child_environment_id_backfills_its_project(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)
        child = self._child_environment()
        database_class = self._patched_database()

        call_command("backfill_metric_lineage", "--team-id", str(child.pk))

        assert database_class.create_for.call_args.kwargs["team"] == self.team
        assert Node.objects.filter(team=self.team, metric_id=metric.id).exists()

    def test_backfill_repairs_a_degraded_node(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_EVENTS)
        with team_scope(self.team.id):
            mark_metric_node_degraded(self.team, metric.id, metric.name, "schema build blew up")

        call_command("backfill_metric_lineage", "--team-id", str(self.team.pk))

        node = Node.objects.get(team=self.team, metric_id=metric.id)
        assert "system" not in node.properties


class TestLineageTaskRegistration(SimpleTestCase):
    def test_the_sync_task_is_registered_from_the_tasks_package(self) -> None:
        # Celery autodiscovery imports the package, not the modules under it. Without the re-export
        # in tasks/__init__.py a worker never registers this task and discards every message.
        package = importlib.import_module("products.data_catalog.backend.tasks")

        assert getattr(package, "tasks", None) is not None
        assert sync_metric_lineage_task.name == "posthog.tasks.data_catalog.sync_metric_lineage"
