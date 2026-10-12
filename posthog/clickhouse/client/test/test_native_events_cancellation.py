from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Event
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.execute import validated_client_query_id
from posthog.clickhouse.query_tagging import get_query_tags, tag_queries
from posthog.clickhouse.workload import Workload


class TestNativeEventsQueryCancellation(SimpleTestCase):
    @override_settings(
        CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER=False
    )
    def test_native_cancellation_deadline_includes_time_spent_on_legacy(self) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        release_native, native_started, native_finished = Event(), Event(), Event()

        def execute(query: str, _parameters: dict[str, str], **kwargs: object) -> Any:
            if "ON CLUSTER" in query:
                native_started.set()
                try:
                    self.assertTrue(release_native.wait(2))
                    return []
                finally:
                    native_finished.set()
            return ([], [("kill_status", "String"), ("query_id", "String")]) if kwargs.get("with_column_types") else []

        with (
            patch("posthog.clickhouse.cancel.monotonic", side_effect=[0, 19.9]),
            patch("posthog.clickhouse.cancel.default_client"),
            patch("posthog.clickhouse.cancel.sync_execute", side_effect=execute),
        ):
            try:
                with self.assertRaises(TimeoutError):
                    cancel_query_on_cluster(44, "example-query")
                self.assertTrue(native_started.is_set())
                self.assertFalse(native_finished.is_set())
            finally:
                release_native.set()
                self.assertTrue(native_finished.wait(1))

    @parameterized.expand([(False,), (True,)])
    @override_settings(
        CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER=False
    )
    def test_saturated_native_cleanup_cannot_report_unconfirmed_cancellation(self, legacy_found: bool) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        with (
            patch("posthog.clickhouse.cancel.submit_native_metadata", return_value=None),
            patch("posthog.clickhouse.cancel.default_client"),
            patch(
                "posthog.clickhouse.cancel.sync_execute",
                side_effect=[[("legacy.example.com", "44_example-query_12345678")], []] if legacy_found else [[]],
            ),
        ):
            if legacy_found:
                cancel_query_on_cluster(44, "example-query")
            else:
                with self.assertRaisesRegex(RuntimeError, "Native query cancellation is busy"):
                    cancel_query_on_cluster(44, "example-query")

    @override_settings(
        CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER=False
    )
    def test_legacy_cancellation_finishes_while_native_is_stalled_and_keeps_tags_isolated(self) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        native_started, release_native, native_finished, legacy_killed = Event(), Event(), Event(), Event()
        native_client, legacy_client = MagicMock(), MagicMock()
        native_client.__enter__.return_value = native_client
        legacy_client.__enter__.return_value = legacy_client
        tag_queries(team_id=44, name="legacy-cancel", client_query_id="example-query")

        def get_client(**kwargs: object) -> MagicMock:
            return native_client if kwargs.get("workload") == Workload.NATIVE_EVENTS else legacy_client

        def execute(query: str, _parameters: dict[str, str], **kwargs: object) -> Any:
            if kwargs["sync_client"] is native_client:
                self.assertIsNone(get_query_tags().team_id)
                self.assertIsNone(get_query_tags().client_query_id)
                get_query_tags().name = "native-thread"
                native_started.set()
                try:
                    self.assertTrue(release_native.wait(3))
                    raise RuntimeError("native unavailable")
                finally:
                    native_finished.set()
            if "distributed_system_processes" in query:
                self.assertIsNone(get_query_tags().client_query_id)
                return [("legacy.example.com", "44_example-query_12345678")]
            legacy_killed.set()
            return ([], [("kill_status", "String"), ("query_id", "String")]) if kwargs.get("with_column_types") else []

        with (
            patch("posthog.clickhouse.cancel.default_client", side_effect=get_client),
            patch("posthog.clickhouse.cancel.sync_execute", side_effect=execute),
            ThreadPoolExecutor(max_workers=1) as caller,
        ):
            future = caller.submit(copy_context().run, cancel_query_on_cluster, 44, "example-query")
            try:
                self.assertTrue(native_started.wait(1))
                self.assertTrue(legacy_killed.wait(0.5))
                future.result(timeout=0.5)
                self.assertEqual(get_query_tags().name, "legacy-cancel")
                self.assertEqual(get_query_tags().client_query_id, "example-query")
            finally:
                release_native.set()
                self.assertTrue(native_finished.wait(1))

    @parameterized.expand(
        [
            (
                "example",
                ["44_example_12345678", "440_example_12345678", "44_example2_12345678"],
                ["44_example_12345678"],
            ),
            ("%", ["44_%_12345678", "44_other_12345678", "440_%_12345678"], ["44_%_12345678"]),
            ("a_b", ["44_a_b_12345678", "44_axb_12345678", "440_a_b_12345678"], ["44_a_b_12345678"]),
            (r"a\b", [r"44_a\b_12345678", "44_ab_12345678"], [r"44_a\b_12345678"]),
            ("a", ["44_a_12345678", "44_a_b_12345678"], ["44_a_12345678"]),
            ("None", ["44_None_12345678", "None_None_12345678"], ["44_None_12345678"]),
        ]
    )
    @override_settings(
        CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER=True
    )
    def test_cancellation_predicates_match_only_literal_team_and_client_id(
        self, query_id: str, candidates: list[str], expected: list[str]
    ) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster
        from posthog.clickhouse.client.connection import default_client

        metadata_ids: list[str] = []
        tag_queries(team_id=44, client_query_id=query_id)

        def capture_metadata_id(_query: str, _parameters: dict[str, str], **kwargs: object) -> Any:
            metadata_id = validated_client_query_id()
            assert metadata_id is not None
            metadata_ids.append(metadata_id)
            return ([], [("kill_status", "String"), ("query_id", "String")]) if kwargs.get("with_column_types") else []

        with (
            patch("posthog.clickhouse.cancel.default_client"),
            patch("posthog.clickhouse.cancel.sync_execute", side_effect=capture_metadata_id) as execute,
        ):
            cancel_query_on_cluster(44, query_id)
        with default_client(database="system") as local_client:
            for call in execute.call_args_list:
                predicate = call.args[0].split("WHERE", 1)[1].split("SETTINGS", 1)[0].strip()
                # nosemgrep: clickhouse-fstring-param-audit - predicate comes from cancellation SQL above
                result = sync_execute(
                    f"SELECT arrayFilter(query_id -> {predicate}, %(candidates)s)",
                    {**call.args[1], "candidates": [*candidates, *metadata_ids]},
                    sync_client=local_client,
                )
                self.assertEqual(result[0][0], expected)

    @parameterized.expand([(False,), (True,)])
    @override_settings(
        CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER=False
    )
    def test_native_failure_is_reported_unless_the_query_is_found_and_cancelled_on_legacy(
        self, legacy_found: bool
    ) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        native_finished = Event()

        def execute(query: str, _parameters: dict[str, str], **kwargs: object) -> Any:
            if "ON CLUSTER" in query:
                native_finished.set()
                raise RuntimeError("native unavailable")
            if "distributed_system_processes" in query and legacy_found:
                return [("legacy.example.com", "44_example-query_12345678")]
            return ([], [("kill_status", "String"), ("query_id", "String")]) if kwargs.get("with_column_types") else []

        with (
            patch("posthog.clickhouse.cancel.default_client"),
            patch("posthog.clickhouse.cancel.sync_execute", side_effect=execute),
        ):
            if legacy_found:
                cancel_query_on_cluster(44, "example-query")
            else:
                with self.assertRaisesRegex(RuntimeError, "native unavailable"):
                    cancel_query_on_cluster(44, "example-query")
            self.assertTrue(native_finished.wait(1))

    @override_settings(
        CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER=False
    )
    def test_cancel_reaches_native_cluster_even_when_legacy_discovery_has_no_query(self) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        with (
            patch("posthog.clickhouse.cancel.default_client") as client,
            patch(
                "posthog.clickhouse.cancel.sync_execute",
                side_effect=lambda *args, **kwargs: (
                    ([], [("kill_status", "String"), ("query_id", "String")]) if kwargs.get("with_column_types") else []
                ),
            ) as execute,
        ):
            cancel_query_on_cluster(44, "example-query")
        native_clients = [
            call for call in client.call_args_list if call.kwargs.get("workload") == Workload.NATIVE_EVENTS
        ]
        self.assertEqual(len(native_clients), 1)
        self.assertEqual(native_clients[0].kwargs["send_receive_timeout"], 15)
        kills = [call for call in execute.call_args_list if "KILL QUERY" in call.args[0]]
        self.assertEqual(len(kills), 1)
        self.assertIn("ON CLUSTER", kills[0].args[0])
        self.assertEqual(kills[0].args[1], {"client_query_id": "44_example-query_"})

    @parameterized.expand(
        [
            (False, False, False),
            (False, True, False),
            (True, False, False),
            (True, True, False),
            (True, False, True),
            (True, True, True),
        ]
    )
    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_legacy_outage_does_not_mask_confirmed_native_cancellation(
        self, fallback: bool, confirmed: bool, discovery_only: bool
    ) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        native_client, legacy_client = MagicMock(), MagicMock()
        native_client.__enter__.return_value = native_client
        legacy_client.__enter__.return_value = legacy_client

        def get_client(**kwargs: object) -> MagicMock:
            return native_client if kwargs.get("workload") == Workload.NATIVE_EVENTS else legacy_client

        def execute(query: str, _parameters: dict[str, str], **kwargs: object) -> Any:
            if kwargs["sync_client"] is legacy_client:
                if not discovery_only or "distributed_system_processes" in query:
                    raise RuntimeError("legacy unavailable")
                return []
            rows = [("waiting", "44_example-query_12345678")] if confirmed else []
            return (
                (rows, [("kill_status", "String"), ("query_id", "String")]) if kwargs.get("with_column_types") else rows
            )

        with (
            override_settings(CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER=fallback),
            patch("posthog.clickhouse.cancel.default_client", side_effect=get_client),
            patch("posthog.clickhouse.cancel.sync_execute", side_effect=execute),
        ):
            if confirmed:
                cancel_query_on_cluster(44, "example-query")
            else:
                with self.assertRaisesRegex(RuntimeError, "legacy unavailable"):
                    cancel_query_on_cluster(44, "example-query")
