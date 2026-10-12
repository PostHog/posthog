import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQuery, HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_user
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models import Organization, Team, User


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestNewEventsSchemaUserRollout(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(id=44, modifiers={}, organization=Organization(id=1))
        self.user = User(id=123, is_staff=True, is_active=True)
        self.modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
        self.settings_patch = patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: '{"44": [123]}' if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_USERS" else False,
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        cookieless = patch(
            "products.web_analytics.backend.hogql_queries.cookieless_flag.resolve_cookieless_traffic_is_regular_modifier",
            return_value=True,
        )
        cookieless.start()
        self.addCleanup(cookieless.stop)

    def test_staff_opt_in_changes_only_that_users_project_default(self) -> None:
        selected = create_default_modifiers_for_user(self.user, self.team, self.modifiers)
        self.assertIs(selected.useNewEventsSchema, True)
        self.assertIsNone(self.modifiers.useNewEventsSchema)
        self.assertIs(
            create_default_modifiers_for_user(
                User(id=124, is_staff=True), self.team, self.modifiers
            ).useNewEventsSchema,
            False,
        )
        self.assertIs(
            create_default_modifiers_for_user(self.user, Team(id=45), self.modifiers).useNewEventsSchema, False
        )

    @parameterized.expand([(False, True), (True, False)])
    def test_nonstaff_and_inactive_users_cannot_inherit_opt_in(self, staff: bool, active: bool) -> None:
        self.user.is_staff, self.user.is_active = staff, active
        self.assertIs(create_default_modifiers_for_user(self.user, self.team, self.modifiers).useNewEventsSchema, False)

    def test_explicit_false_is_the_comparison_and_rollback_control(self) -> None:
        self.modifiers.useNewEventsSchema = False
        self.assertIs(create_default_modifiers_for_user(self.user, self.team, self.modifiers).useNewEventsSchema, False)

    def test_team_false_overrides_user_default(self) -> None:
        self.team.modifiers = {"useNewEventsSchema": False}
        self.assertIs(create_default_modifiers_for_user(self.user, self.team, self.modifiers).useNewEventsSchema, False)

    @parameterized.expand([("not json",), ('{"44": true}',), ('{"44": ["123"]}',), ('{"44": [true]}',)])
    def test_malformed_enrollment_fails_closed(self, enrollment: str) -> None:
        with patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: enrollment if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_USERS" else False,
        ):
            self.assertIs(
                create_default_modifiers_for_user(self.user, self.team, self.modifiers).useNewEventsSchema, False
            )

    def test_query_runner_resolves_user_default_before_cache_lookup(self) -> None:
        runner = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team, user=self.user
        )
        self.assertIs(runner.modifiers.useNewEventsSchema, True)

    def test_changing_query_actor_resets_only_the_inherited_table_choice(self) -> None:
        runner = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team, user=self.user
        )
        self.assertIs(runner.modifiers.useNewEventsSchema, True)
        runner.user = User(id=124, is_staff=True)
        runner._on_user_changed()
        self.assertIs(runner.modifiers.useNewEventsSchema, False)

    def test_user_supplied_at_run_is_resolved_before_cache_lookup(self) -> None:
        runner = HogQLQueryRunner(query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team)
        with patch.object(runner, "get_cache_key", side_effect=RuntimeError("cache boundary")):
            with self.assertRaisesRegex(RuntimeError, "cache boundary"):
                runner.run(user=self.user)
        self.assertIs(runner.modifiers.useNewEventsSchema, True)

    def test_async_query_serializes_effective_table_without_changing_saved_source(self) -> None:
        source = HogQLQuery(query="SELECT 1", modifiers=self.modifiers)
        runner = HogQLQueryRunner(query=source, team=self.team, user=self.user)
        cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            runner.enqueue_async_calculation(cache_manager=cache, user=self.user)
        self.assertIs(enqueue.call_args.kwargs["query_json"]["modifiers"]["useNewEventsSchema"], True)
        assert source.modifiers is not None
        self.assertIsNone(source.modifiers.useNewEventsSchema)

    def test_async_effective_modifier_has_same_cache_payload_as_request(self) -> None:
        request = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team, user=self.user
        )
        effective = self.modifiers.model_copy(update={"useNewEventsSchema": True})
        worker = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT 1", modifiers=effective), team=self.team, user=self.user
        )
        with (
            patch.object(request, "_get_property_access_restrictions", return_value=None),
            patch.object(worker, "_get_property_access_restrictions", return_value=None),
            patch.object(request, "_products_modifiers_for_cache", return_value={}),
            patch.object(worker, "_products_modifiers_for_cache", return_value={}),
            patch("posthog.hogql_queries.query_runner.events_retention_months_for_team", return_value=None),
        ):
            self.assertEqual(request.get_cache_payload(), worker.get_cache_payload())

    def test_legacy_default_retains_cache_namespace_when_choice_is_resolved(self) -> None:
        runner = HogQLQueryRunner(query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team)
        with (
            patch.object(runner, "_get_property_access_restrictions", return_value=None),
            patch.object(runner, "_products_modifiers_for_cache", return_value={}),
            patch("posthog.hogql_queries.query_runner.events_retention_months_for_team", return_value=None),
        ):
            payload = runner.get_cache_payload()
        self.assertIs(runner.modifiers.useNewEventsSchema, False)
        self.assertNotIn("useNewEventsSchema", payload["hogql_modifiers"])

    def test_resolved_legacy_choice_cannot_change_after_enrollment_changes(self) -> None:
        ordinary = User(id=124, is_staff=True, is_active=True)
        initial = create_default_modifiers_for_user(ordinary, self.team, self.modifiers)
        with patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: '{"44": [124]}' if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_USERS" else False,
        ):
            self.assertIs(create_default_modifiers_for_user(ordinary, self.team, initial).useNewEventsSchema, False)

    def test_direct_hogql_execution_resolves_the_same_user_default(self) -> None:
        executor = HogQLQueryExecutor(query="SELECT 1", team=self.team, user=self.user, modifiers=self.modifiers)
        self.assertIs(executor.query_modifiers.useNewEventsSchema, True)

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_native_table_executes_on_native_workload(self) -> None:
        executor = HogQLQueryExecutor(query="SELECT 1", team=self.team, user=self.user, modifiers=self.modifiers)
        executor.clickhouse_sql = "SELECT 1"
        executor.clickhouse_context = HogQLContext(
            team_id=self.team.pk, modifiers=HogQLQueryModifiers(useNewEventsSchema=True)
        )
        executor.select_query = ast.SelectQuery(select=[ast.Constant(value=1)])
        with (
            patch.object(executor, "_plan_fingerprint", return_value="example"),
            patch.object(executor, "_detect_warehouse_sources"),
            patch("posthog.hogql.query.sync_execute", return_value=([(1,)], [("1", "UInt8")])) as execute,
        ):
            executor._execute_clickhouse_query()
        self.assertEqual(execute.call_args.kwargs["workload"].value, "NATIVE_EVENTS")

    @parameterized.expand(
        [
            (None, True, Workload.DEFAULT),
            ("native.example.com", False, Workload.DEFAULT),
            ("native.example.com", True, Workload.LOGS),
        ]
    )
    def test_unconfigured_legacy_and_logs_queries_keep_existing_route(
        self, host: str | None, native: bool, workload: Workload
    ) -> None:
        with override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST=host):
            executor = HogQLQueryExecutor(query="SELECT 1", team=self.team, modifiers=self.modifiers, workload=workload)
            executor.clickhouse_sql = "SELECT 1"
            executor.clickhouse_context = HogQLContext(
                team_id=self.team.pk, modifiers=HogQLQueryModifiers(useNewEventsSchema=native)
            )
            executor.select_query = ast.SelectQuery(select=[ast.Constant(value=1)])
            with (
                patch.object(executor, "_plan_fingerprint", return_value="example"),
                patch.object(executor, "_detect_warehouse_sources"),
                patch("posthog.hogql.query.sync_execute", return_value=([(1,)], [("1", "UInt8")])) as execute,
            ):
                executor._execute_clickhouse_query()
            self.assertEqual(execute.call_args.kwargs["workload"], workload)


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False, CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
class TestNativeEventsUserQueryRouting(APIBaseTest):
    def test_user_opt_in_and_explicit_legacy_control_reach_the_correct_workloads(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        enrollment = json.dumps({str(self.team.id): [self.user.id]})
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: enrollment if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_USERS" else False,
            ),
            patch("posthog.hogql.query.sync_execute", return_value=([(7,)], [("n", "UInt64")])) as execute,
        ):
            native = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {
                    "query": {"kind": "HogQLQuery", "query": "SELECT count() AS n FROM events"},
                    "refresh": "force_blocking",
                },
                format="json",
            )
            self.assertEqual(native.status_code, 200, native.json())
            self.assertIs(native.json()["modifiers"]["useNewEventsSchema"], True)
            self.assertEqual(execute.call_args.kwargs["workload"], Workload.NATIVE_EVENTS)
            self.assertIn("events_json", execute.call_args.args[0])
            legacy = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "SELECT count() AS n FROM events",
                        "modifiers": {"useNewEventsSchema": False},
                    },
                    "refresh": "force_blocking",
                },
                format="json",
            )
            self.assertEqual(legacy.status_code, 200, legacy.json())
            self.assertIs(legacy.json()["modifiers"]["useNewEventsSchema"], False)
            self.assertNotEqual(execute.call_args.kwargs["workload"], Workload.NATIVE_EVENTS)
            self.assertNotIn("events_json", execute.call_args.args[0])
            self.assertNotEqual(native.json()["cache_key"], legacy.json()["cache_key"])
