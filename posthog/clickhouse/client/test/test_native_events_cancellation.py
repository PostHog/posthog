import json
from concurrent.futures import Future
from threading import Event
from typing import Any

from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.metadata_worker import run_metadata_job
from posthog.clickhouse.query_tagging import tag_queries


class TestNativeEventsQueryCancellation(SimpleTestCase):
    def setUp(self) -> None:
        patcher = patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: getattr(settings, "CLICKHOUSE_NATIVE_EVENTS_HOST", ""),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        worker = patch(
            "posthog.clickhouse.native_metadata._run_metadata_process",
            side_effect=lambda payload, _: run_metadata_job(json.loads(payload)),
        )
        worker.start()
        self.addCleanup(worker.stop)

    @parameterized.expand([("legacy",), ("native",)])
    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_cancellation_deadline_bounds_either_stalled_cluster(self, stalled: str) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        legacy: Future[bool] = Future()
        native: Future[bool] = Future()
        (native if stalled == "legacy" else legacy).set_result(False)
        with (
            patch("posthog.clickhouse.cancel.monotonic", side_effect=[0, 20, 20]),
            patch("posthog.clickhouse.cancel.submit_legacy_metadata", return_value=legacy),
            patch("posthog.clickhouse.cancel.submit_native_metadata", return_value=native),
        ):
            with self.assertRaises(TimeoutError):
                cancel_query_on_cluster(44, "example-query")

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_confirmed_native_cleanup_does_not_wait_for_stalled_legacy(self) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        legacy: Future[bool] = Future()
        native: Future[bool] = Future()
        native.set_result(True)
        with (
            patch("posthog.clickhouse.cancel.submit_legacy_metadata", return_value=legacy),
            patch("posthog.clickhouse.cancel.submit_native_metadata", return_value=native),
        ):
            cancel_query_on_cluster(44, "example-query")
        self.assertFalse(legacy.done())

    @parameterized.expand([("legacy",), ("native",)])
    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_connection_preparation_failure_does_not_block_the_other_cluster(self, failed: str) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        healthy: Future[bool] = Future()
        healthy.set_result(True)
        failure = RuntimeError("credentials unavailable")
        with (
            patch(
                "posthog.clickhouse.cancel.metadata_connection",
                side_effect=[failure, {}] if failed == "legacy" else [{}, failure],
            ),
            patch("posthog.clickhouse.cancel.submit_legacy_metadata", return_value=healthy),
            patch("posthog.clickhouse.cancel.submit_native_metadata", return_value=healthy),
        ):
            cancel_query_on_cluster(44, "example-query")

    def test_legacy_cancellation_survives_native_host_setting_failure(self) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        with (
            patch(
                "posthog.clickhouse.cancel.get_new_events_cluster_host",
                side_effect=RuntimeError("settings unavailable"),
            ),
            patch("posthog.clickhouse.cancel.default_client"),
            patch(
                "posthog.clickhouse.cancel.sync_execute",
                side_effect=[[("legacy.example.com", "44_example-query_12345678")], []],
            ) as execute,
        ):
            cancel_query_on_cluster(44, "example-query")
        self.assertIn("KILL QUERY", execute.call_args.args[0])
        self.assertEqual(execute.call_args.args[1], {"query_id": "44_example-query_12345678"})

    @parameterized.expand([(False,), (True,)])
    @override_settings(
        CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER=False
    )
    def test_saturated_native_cleanup_cannot_report_unconfirmed_cancellation(self, legacy_found: bool) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        with (
            patch("posthog.clickhouse.cancel.submit_native_metadata", return_value=None),
            patch("posthog.clickhouse.cancel.submit_legacy_metadata") as submit_legacy,
        ):
            legacy: Future[bool] = Future()
            legacy.set_result(legacy_found)
            submit_legacy.return_value = legacy
            if legacy_found:
                cancel_query_on_cluster(44, "example-query")
            else:
                with self.assertRaisesRegex(RuntimeError, "Native query cancellation is busy"):
                    cancel_query_on_cluster(44, "example-query")

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

        tag_queries(team_id=44, client_query_id=query_id)

        with (
            patch("posthog.clickhouse.metadata_worker.Client") as client,
        ):
            execute = client.return_value.__enter__.return_value.execute
            execute.return_value = []
            cancel_query_on_cluster(44, query_id)
        with default_client(database="system") as local_client:
            for call in execute.call_args_list:
                self.assertNotIn("query_id", call.kwargs)
                tags = json.loads(call.kwargs["settings"]["log_comment"])
                self.assertIsNone(tags.get("team_id"))
                self.assertIsNone(tags.get("client_query_id"))
                predicate = call.args[0].split("WHERE", 1)[1].split("SETTINGS", 1)[0].strip()
                # nosemgrep: clickhouse-fstring-param-audit - predicate comes from cancellation SQL above
                result = sync_execute(
                    f"SELECT arrayFilter(query_id -> {predicate}, %(candidates)s)",
                    {**call.args[1], "candidates": candidates},
                    sync_client=local_client,
                )
                self.assertEqual(result[0][0], expected)

    @parameterized.expand(
        [
            (False, False, "empty", None, None),
            (False, False, "unavailable", None, "native unavailable"),
            (False, True, "unavailable", None, None),
        ]
        + [
            (fallback, False, "confirmed" if confirmed else "empty", "all", None if confirmed else "legacy unavailable")
            for fallback in (False, True)
            for confirmed in (False, True)
        ]
        + [
            (
                True,
                False,
                "confirmed" if confirmed else "empty",
                "discovery",
                None if confirmed else "legacy unavailable",
            )
            for confirmed in (False, True)
        ]
    )
    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_cancellation_survives_an_unavailable_cluster_only_when_cleanup_is_confirmed(
        self, fallback: bool, legacy_found: bool, native_result: str, legacy_failure: str | None, error: str | None
    ) -> None:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        native_finished = Event()
        native_client, legacy_client = MagicMock(), MagicMock()
        native_client.__enter__.return_value = native_client
        legacy_client.__enter__.return_value = legacy_client

        def get_client(**kwargs: object) -> MagicMock:
            return native_client if kwargs.get("host") == "native.example.com" else legacy_client

        def execute(query: str, _parameters: dict[str, str], **kwargs: object) -> Any:
            if kwargs["sync_client"] is legacy_client:
                discovery = "distributed_system_processes" in query
                if legacy_failure == "all" or legacy_failure == "discovery" and discovery:
                    raise RuntimeError("legacy unavailable")
                return [("legacy.example.com", "44_example-query_12345678")] if discovery and legacy_found else []
            try:
                if native_result == "unavailable":
                    raise RuntimeError("native unavailable")
                if "system.processes" in query:
                    return [("native.example.com", "44_example-query_12345678")] if native_result == "confirmed" else []
                return [("finished", "44_example-query_12345678")], [("kill_status", "String"), ("query_id", "String")]
            finally:
                native_finished.set()

        with (
            override_settings(CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER=fallback),
            patch("posthog.clickhouse.metadata_worker.Client", side_effect=get_client) as client,
        ):
            native_client.execute.side_effect = lambda sql, params, **kwargs: execute(
                sql, params, sync_client=native_client, **kwargs
            )
            legacy_client.execute.side_effect = lambda sql, params, **kwargs: execute(
                sql, params, sync_client=legacy_client, **kwargs
            )
            if error:
                with self.assertRaisesRegex(RuntimeError, error):
                    cancel_query_on_cluster(44, "example-query")
            else:
                cancel_query_on_cluster(44, "example-query")
            self.assertTrue(native_finished.wait(1))
        native_calls = [call for call in client.call_args_list if call.kwargs.get("host") == "native.example.com"]
        self.assertEqual(len(native_calls), 2 if native_result == "confirmed" else 1)
        self.assertEqual(native_calls[0].kwargs["send_receive_timeout"], 15)
        native_kills = [call for call in native_client.execute.call_args_list if "KILL" in call.args[0]]
        self.assertEqual(len(native_kills), 1 if native_result == "confirmed" else 0)
        if native_kills:
            self.assertIn("SYNC", native_kills[0].args[0])
            self.assertNotIn("ON CLUSTER", native_kills[0].args[0])
            self.assertEqual(native_kills[0].args[1], {"query_id": "44_example-query_12345678"})
