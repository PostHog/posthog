from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from queue import Queue
from threading import Event
from time import monotonic

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from django.db import OperationalError, connection, transaction
from django.db.models import QuerySet

from parameterized import parameterized

from posthog.models import Team

from products.customer_analytics.backend.events import emit_account_custom_property_changed
from products.customer_analytics.backend.logic.custom_property_values import (
    MIN_INTERVAL_BETWEEN_LAST_SLACK_MESSAGE_WRITES,
    SyncedCustomPropertyValuesResult,
    record_last_slack_message_at,
    set_account_custom_properties_by_id,
    set_custom_property_value,
    set_synced_custom_property_value,
    set_synced_custom_property_values,
)
from products.customer_analytics.backend.models import Account, CustomPropertyDefinition, CustomPropertyValue
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition

LOGIC_MODULE = "products.customer_analytics.backend.logic.custom_property_values"
_WAIT_TIMEOUT_SECONDS = 10


class TestCustomPropertyValueConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.account = create_account(team_id=self.team.id)
        self.definition = create_custom_property_definition(team_id=self.team.id)
        self.worker_pids: Queue[int] = Queue()
        event_patch = patch(f"{LOGIC_MODULE}.emit_account_custom_property_changed")
        self.value_changed = event_patch.start()
        self.addCleanup(event_patch.stop)

    def _set(
        self,
        value: str,
        *,
        account: Account | None = None,
        definition: CustomPropertyDefinition | None = None,
        team_id: int | None = None,
    ) -> CustomPropertyValue:
        return set_custom_property_value(
            team_id=team_id if team_id is not None else self.team.id,
            account_id=str((account or self.account).id).upper(),
            definition_id=(definition or self.definition).id,
            value=value,
        )

    def _write(self, operation: str, value: str) -> object:
        if operation == "set":
            return self._set(value)
        return set_account_custom_properties_by_id(
            team_id=self.team.id,
            account_id=self.account.id,
            properties={str(self.definition.id): None},
        )

    def _start_write(self, executor: ThreadPoolExecutor, write: Callable[[], object]) -> Future[object]:
        def run() -> object:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    self.worker_pids.put(cursor.fetchone()[0])
                return write()
            finally:
                connection.close()

        return executor.submit(run)

    def _assert_write_waits(self, future: Future[object], holder_pid: int | None = None) -> None:
        worker_pid = self.worker_pids.get(timeout=_WAIT_TIMEOUT_SECONDS)
        deadline = monotonic() + _WAIT_TIMEOUT_SECONDS
        with connection.cursor() as cursor:
            if holder_pid is None:
                cursor.execute("SELECT pg_backend_pid()")
                holder_pid = cursor.fetchone()[0]
            while monotonic() < deadline:
                if future.done():
                    future.result()
                    self.fail("The competing write finished before the holder transaction ended")
                cursor.execute("SELECT %s = ANY(pg_blocking_pids(%s))", [holder_pid, worker_pid])
                if cursor.fetchone()[0]:
                    return
        self.fail("The competing write did not wait for the holder transaction")

    @parameterized.expand(
        [
            ("first_insert", None, "set", "set", "second", 2),
            ("replacement", "initial", "set", "set", "second", 3),
            ("set_then_clear", "initial", "set", "clear", None, 2),
            ("clear_then_set", "initial", "clear", "set", "second", 2),
            ("absent_clear_then_set", None, "clear", "set", "second", 1),
            ("clear_then_clear", "initial", "clear", "clear", None, 1),
        ]
    )
    def test_same_key_writes_wait_for_commit_and_preserve_history(
        self,
        _name: str,
        initial: str | None,
        first_operation: str,
        second_operation: str,
        expected: str | None,
        history_count: int,
    ) -> None:
        if initial is not None:
            self._set(initial)
        self.value_changed.reset_mock()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                self._write(first_operation, "first")
                future = self._start_write(executor, lambda: self._write(second_operation, "second"))
                self._assert_write_waits(future)
            future.result(timeout=_WAIT_TIMEOUT_SECONDS)

        rows = CustomPropertyValue.objects.for_team(self.team.id).filter(
            account=self.account, definition=self.definition
        )
        self.assertEqual(rows.count(), history_count)
        self.assertEqual(
            list(rows.filter(is_deleted=False).values_list("value_str", flat=True)), [expected] if expected else []
        )
        expected_events: list[tuple[str | None, str | None]] = []
        previous = initial
        for operation, value in [(first_operation, "first"), (second_operation, "second")]:
            current = value if operation == "set" else None
            if previous != current:
                expected_events.append((previous, current))
            previous = current
        self.assertCountEqual(
            [
                (call.kwargs["previous_value"], call.kwargs["current_value"])
                for call in self.value_changed.call_args_list
            ],
            expected_events,
        )

    @parameterized.expand(
        [
            ("scalar_same_value", "enterprise", False, 2, False),
            ("scalar_previous_value", "starter", True, 3, False),
            ("batch_same_value", "enterprise", False, 2, True),
            ("batch_previous_value", "starter", True, 3, True),
        ]
    )
    def test_sync_checks_current_value_after_the_competing_write_commits(
        self, _name: str, value: str, changed: bool, history_count: int, batch: bool
    ) -> None:
        self._set("starter")
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                self._set("enterprise")
                future = self._start_write(
                    executor,
                    lambda: (
                        bool(
                            set_synced_custom_property_values(
                                team_id=self.team.id, definition=self.definition, values={self.account.id: value}
                            ).written
                        )
                        if batch
                        else set_synced_custom_property_value(
                            team_id=self.team.id,
                            account_id=self.account.id,
                            definition=self.definition,
                            value=value,
                        )
                    ),
                )
                self._assert_write_waits(future)
            self.assertIs(future.result(timeout=_WAIT_TIMEOUT_SECONDS), changed)

        rows = CustomPropertyValue.objects.for_team(self.team.id).filter(
            account=self.account, definition=self.definition
        )
        self.assertEqual(rows.count(), history_count)
        self.assertEqual(rows.get(is_deleted=False).value_str, value)

    def test_rollback_releases_the_key_without_history_or_events_from_the_failed_write(self) -> None:
        self._set("initial")
        self.value_changed.reset_mock()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                self._set("rolled back")
                future = self._start_write(executor, lambda: self._set("accepted"))
                self._assert_write_waits(future)
                transaction.set_rollback(True)
            future.result(timeout=_WAIT_TIMEOUT_SECONDS)

        rows = CustomPropertyValue.objects.for_team(self.team.id).filter(
            account=self.account, definition=self.definition
        )
        self.assertCountEqual(rows.values_list("value_str", flat=True), ["initial", "accepted"])
        self.assertEqual(rows.get(is_deleted=False).value_str, "accepted")
        self.value_changed.assert_called_once()
        self.assertEqual(self.value_changed.call_args.kwargs["previous_value"], "initial")
        self.assertEqual(self.value_changed.call_args.kwargs["current_value"], "accepted")

    @parameterized.expand([("account",), ("definition",)])
    def test_other_keys_do_not_wait_for_the_holder_transaction(self, different_key: str) -> None:
        account = create_account(team_id=self.team.id) if different_key == "account" else self.account
        definition = (
            create_custom_property_definition(team_id=self.team.id, name="Other")
            if different_key == "definition"
            else self.definition
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                self._set("first")
                future = self._start_write(
                    executor, lambda: self._set("second", account=account, definition=definition)
                )
                future.result(timeout=_WAIT_TIMEOUT_SECONDS)
        self.assertEqual(
            CustomPropertyValue.objects.for_team(self.team.id)
            .get(account=account, definition=definition, is_deleted=False)
            .value_str,
            "second",
        )

    @parameterized.expand([("scalar",), ("batch",)])
    def test_environment_and_parent_writes_share_the_same_key(self, writer: str) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Environment")
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                self._set("first")
                future = self._start_write(
                    executor,
                    lambda: (
                        set_synced_custom_property_values(
                            team_id=environment.id, definition=self.definition, values={self.account.id: "second"}
                        )
                        if writer == "batch"
                        else self._set("second", team_id=environment.id)
                    ),
                )
                self._assert_write_waits(future)
            future.result(timeout=_WAIT_TIMEOUT_SECONDS)
        self.assertEqual(
            CustomPropertyValue.objects.for_team(self.team.id)
            .get(account=self.account, definition=self.definition, is_deleted=False)
            .value_str,
            "second",
        )

    def test_reversed_batches_acquire_keys_in_the_same_order(self) -> None:
        other = create_custom_property_definition(team_id=self.team.id, name="Other")
        lower, higher = sorted([self.definition, other], key=lambda definition: definition.id)

        def write_batch() -> object:
            with transaction.atomic():
                return set_account_custom_properties_by_id(
                    team_id=self.team.id,
                    account_id=self.account.id,
                    properties={higher.id.hex.upper(): "second", str(lower.id): "second"},
                )

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '15s'")
                self._set("first", definition=lower)
                future = self._start_write(executor, write_batch)
                self._assert_write_waits(future)
                self._set("first", definition=higher)
            future.result(timeout=_WAIT_TIMEOUT_SECONDS)
        self.assertEqual(
            list(
                CustomPropertyValue.objects.for_team(self.team.id)
                .filter(account=self.account, is_deleted=False)
                .values_list("value_str", flat=True)
            ),
            ["second", "second"],
        )

    def test_retry_keeps_earlier_committed_chunks_without_duplicate_history_or_events(self) -> None:
        accounts = [self.account, create_account(team_id=self.team.id), create_account(team_id=self.team.id)]
        for account in accounts:
            self._set("initial", account=account)
        self.value_changed.reset_mock()
        self.value_changed.side_effect = emit_account_custom_property_changed
        emitted_in_transaction: list[bool] = []

        def capture(**_kwargs: object) -> MagicMock:
            emitted_in_transaction.append(connection.in_atomic_block)
            return MagicMock()

        capture_patch = patch("products.customer_analytics.backend.events.capture_batch_internal", side_effect=capture)
        capture_patch.start()
        self.addCleanup(capture_patch.stop)
        bulk_create = QuerySet.bulk_create
        writes = 0

        def fail_second_chunk(
            queryset: QuerySet[CustomPropertyValue], rows: list[CustomPropertyValue]
        ) -> list[CustomPropertyValue]:
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OperationalError("synthetic chunk failure")
            return bulk_create(queryset, rows)

        values = {account.id: "changed" for account in accounts}
        with patch(f"{LOGIC_MODULE}._SYNC_WRITE_CHUNK_SIZE", 2):
            with patch.object(QuerySet, "bulk_create", autospec=True, side_effect=fail_second_chunk):
                with self.assertRaises(OperationalError):
                    set_synced_custom_property_values(team_id=self.team.id, definition=self.definition, values=values)
            rows = CustomPropertyValue.objects.for_team(self.team.id).filter(definition=self.definition)
            assert rows.count() == 5
            assert dict(rows.filter(is_deleted=False).values_list("account_id", "value_str")) == {
                accounts[0].id: "changed",
                accounts[1].id: "changed",
                accounts[2].id: "initial",
            }
            assert self.value_changed.call_count == 2
            result = set_synced_custom_property_values(team_id=self.team.id, definition=self.definition, values=values)
        assert result.written == 1
        assert result.accepted_account_ids == set(values)
        assert rows.count() == 6
        assert rows.filter(is_deleted=False, value_str="changed").count() == 3
        assert self.value_changed.call_count == 3
        assert emitted_in_transaction == [False, False, False]
        assert {call.kwargs["account"].id for call in self.value_changed.call_args_list} == set(values)
        assert all(
            call.kwargs["previous_value"] == "initial" and call.kwargs["current_value"] == "changed"
            for call in self.value_changed.call_args_list
        )

    @parameterized.expand([("batch",), ("scalar",)])
    def test_overlapping_writers_serialize_against_a_batch(self, writer: str) -> None:
        other = create_account(team_id=self.team.id)
        locks_held = Event()
        release = Event()

        def hold_batch() -> SyncedCustomPropertyValuesResult:
            def hold_after_locks(
                execute: Callable[..., object], sql: str, params: object, many: bool, context: object
            ) -> object:
                result = execute(sql, params, many, context)
                if "pg_advisory_xact_lock" in sql:
                    locks_held.set()
                    assert release.wait(timeout=_WAIT_TIMEOUT_SECONDS)
                return result

            with connection.execute_wrapper(hold_after_locks):
                return set_synced_custom_property_values(
                    team_id=self.team.id,
                    definition=self.definition,
                    values={self.account.id: "shared", other.id: "shared"},
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            holder = self._start_write(executor, hold_batch)
            holder_pid = self.worker_pids.get(timeout=_WAIT_TIMEOUT_SECONDS)
            try:
                assert locks_held.wait(timeout=_WAIT_TIMEOUT_SECONDS)
                competing = self._start_write(
                    executor,
                    lambda: (
                        set_synced_custom_property_values(
                            team_id=self.team.id,
                            definition=self.definition,
                            values={other.id: "shared", self.account.id: "shared"},
                        )
                        if writer == "batch"
                        else self._set("shared")
                    ),
                )
                self._assert_write_waits(competing, holder_pid=holder_pid)
            finally:
                release.set()
            held_result = holder.result(timeout=_WAIT_TIMEOUT_SECONDS)
            assert isinstance(held_result, SyncedCustomPropertyValuesResult)
            assert held_result.written == 2
            competing_result = competing.result(timeout=_WAIT_TIMEOUT_SECONDS)
            if writer == "batch":
                assert isinstance(competing_result, SyncedCustomPropertyValuesResult)
                assert competing_result.written == 0
        rows = CustomPropertyValue.objects.for_team(self.team.id).filter(definition=self.definition)
        assert rows.count() == (2 if writer == "batch" else 3)
        assert rows.filter(is_deleted=False, value_str="shared").count() == 2
        assert self.value_changed.call_count == 2

    def test_slack_timestamp_check_sees_the_committed_newer_value(self) -> None:
        initial = datetime(2026, 1, 1, tzinfo=UTC)
        record_last_slack_message_at(team_id=self.team.id, account_id=self.account.id, timestamp=initial)
        newer = initial + 2 * MIN_INTERVAL_BETWEEN_LAST_SLACK_MESSAGE_WRITES
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                record_last_slack_message_at(team_id=self.team.id, account_id=self.account.id, timestamp=newer)
                future = self._start_write(
                    executor,
                    lambda: record_last_slack_message_at(
                        team_id=self.team.id,
                        account_id=self.account.id,
                        timestamp=initial + MIN_INTERVAL_BETWEEN_LAST_SLACK_MESSAGE_WRITES,
                    ),
                )
                self._assert_write_waits(future)
            self.assertIs(future.result(timeout=_WAIT_TIMEOUT_SECONDS), False)
        self.assertEqual(
            CustomPropertyValue.objects.for_team(self.team.id)
            .get(account=self.account, is_deleted=False)
            .value_datetime,
            newer,
        )
