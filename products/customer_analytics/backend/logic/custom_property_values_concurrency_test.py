import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import Barrier

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import Mock, patch

from django.db import OperationalError, connections, router, transaction
from django.test import override_settings

from parameterized import parameterized

from posthog.dataclasses import frozen
from posthog.models import Team

from products.customer_analytics.backend.logic.custom_property_values import (
    CustomPropertyValueConflict,
    guard_custom_property_value,
    record_last_slack_message_at,
    set_account_custom_properties_by_id,
    set_custom_property_value,
    set_synced_custom_property_value,
)
from products.customer_analytics.backend.models import (
    CANONICAL_LAST_SLACK_MESSAGE_AT,
    Account,
    CustomPropertyDefinition,
    CustomPropertyValue,
    DisplayType,
)

_LOGIC = "products.customer_analytics.backend.logic.custom_property_values"


@frozen
class _PropertyChange:
    previous_value: object
    current_value: object


@override_settings(ACCOUNT_PROPERTY_SYNC_COORDINATION_ENABLED=True)
class CustomPropertyValueConcurrencyTest(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.using = router.db_for_write(CustomPropertyValue)
        self.account = Account.objects.for_team(self.team.id).create(team_id=self.team.id, name="Example account")
        self.definition = CustomPropertyDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="Plan"
        )
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(self.pool.shutdown, wait=True)
        self.events: Mock = self.enterContext(patch(f"{_LOGIC}.emit_account_custom_property_changed"))
        self.enterContext(patch(f"{_LOGIC}._CUSTOM_PROPERTY_VALUE_LOCK_TIMEOUT_MS", 30000))
        with connections[self.using].cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            self.holder_pid = cursor.fetchone()[0]
        self.writer_pid = 0

    def _set(self, value: str) -> CustomPropertyValue:
        return set_custom_property_value(
            team_id=self.team.id,
            account_id=self.account.id,
            definition_id=self.definition.id,
            value=value,
        )

    def _clear(self) -> list[CustomPropertyValue]:
        return set_account_custom_properties_by_id(
            team_id=self.team.id, account_id=self.account.id, properties={str(self.definition.id): None}
        )

    def _sync(self, value: str | None) -> bool:
        return set_synced_custom_property_value(
            team_id=self.team.id, account_id=self.account.id, definition=self.definition, value=value
        )

    def _start_writer(self, work: Callable[[], object]) -> Future[object]:
        pids: Queue[int] = Queue()
        start = Barrier(2)

        def run() -> object:
            connection = connections[self.using]
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.put(cursor.fetchone()[0])
                start.wait(timeout=10)
                return work()
            finally:
                connection.close()

        future = self.pool.submit(run)
        self.writer_pid = pids.get(timeout=10)
        assert self.writer_pid != self.holder_pid
        start.wait(timeout=10)
        return future

    def _wait_until_blocked(self, future: Future[object]) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connections[self.using].cursor() as cursor:
                cursor.execute("SELECT %s = ANY(pg_blocking_pids(%s))", [self.holder_pid, self.writer_pid])
                if cursor.fetchone()[0]:
                    return
            if future.done():
                self.fail(f"The writer finished before the outer transaction ended: {future.result()!r}")
        self.fail("The writer did not reach the held transaction's lock")

    def _history(self) -> Counter[tuple[str | None, bool]]:
        return Counter(
            CustomPropertyValue.objects.for_team(self.team.id)
            .using(self.using)
            .filter(account_id=self.account.id, definition_id=self.definition.id)
            .values_list("value_str", "is_deleted")
        )

    def _event_values(self) -> Counter[_PropertyChange]:
        return Counter(
            _PropertyChange(previous_value=call.kwargs["previous_value"], current_value=call.kwargs["current_value"])
            for call in self.events.call_args_list
        )

    @parameterized.expand(
        [
            ("first_insert", None, "first", "set", "second", False),
            ("replacement", "initial", "first", "set", "second", False),
            ("set_then_clear", None, "first", "clear", None, False),
            ("clear_then_set", "initial", None, "set", "second", False),
            ("absent_clear_then_set", None, None, "set", "second", False),
            ("synced_dedup", None, "first", "sync", "first", False),
            ("synced_stale_dedup", "initial", "first", "sync", "initial", False),
            ("synced_clear", None, "first", "sync", None, False),
            ("insert_rollback", None, "first", "set", "second", True),
            ("replacement_rollback", "initial", "first", "set", "second", True),
            ("clear_rollback", "initial", None, "set", "second", True),
        ]
    )
    def test_writers_serialize_through_outer_commit_or_rollback(
        self,
        _name: str,
        initial: str | None,
        held_value: str | None,
        operation: str,
        next_value: str | None,
        rollback: bool,
    ) -> None:
        if initial is not None:
            self._set(initial)
        self.events.reset_mock()

        def write() -> object:
            if operation == "clear":
                return self._clear()
            if operation == "sync":
                return self._sync(next_value)
            assert next_value is not None
            return self._set(next_value)

        with transaction.atomic(using=self.using):
            if held_value is None:
                self._clear()
            else:
                self._set(held_value)
            assert not self.events.called
            future = self._start_writer(write)
            self._wait_until_blocked(future)
            if rollback:
                transaction.set_rollback(True, using=self.using)

        result = future.result(timeout=10)
        current = initial if rollback else held_value
        expected_history: Counter[tuple[str | None, bool]] = Counter()
        expected_events: Counter[_PropertyChange] = Counter()
        if initial is not None:
            expected_history[(initial, not rollback)] += 1
        if not rollback:
            if held_value is not None:
                expected_history[(held_value, False)] += 1
            if initial != held_value:
                expected_events[_PropertyChange(previous_value=initial, current_value=held_value)] += 1
        dedup = operation == "sync" and current == next_value
        if operation == "sync":
            assert result is (not dedup)
        if not dedup:
            if current is not None:
                expected_history[(current, False)] -= 1
                expected_history[(current, True)] += 1
            if next_value is not None:
                expected_history[(next_value, False)] += 1
            if current != next_value:
                expected_events[_PropertyChange(previous_value=current, current_value=next_value)] += 1
        assert self._history() == +expected_history
        assert self._event_values() == expected_events

    @parameterized.expand([("team",), ("account",), ("definition",)])
    def test_different_keys_can_commit_while_the_first_key_is_guarded(self, different: str) -> None:
        team_id, account_id, definition_id = self.team.id, self.account.id, self.definition.id
        if different == "team":
            team = Team.objects.create(organization=self.organization)
            team_id = team.id
            account_id = Account.objects.for_team(team_id).create(team_id=team_id, name="Other account").id
            definition_id = CustomPropertyDefinition.objects.for_team(team_id).create(team_id=team_id, name="Plan").id
        elif different == "account":
            account_id = Account.objects.for_team(team_id).create(team_id=team_id, name="Other account").id
        else:
            definition_id = CustomPropertyDefinition.objects.for_team(team_id).create(team_id=team_id, name="Seats").id

        with transaction.atomic(using=self.using):
            self._set("first")
            future = self._start_writer(
                lambda: set_custom_property_value(
                    team_id=team_id, account_id=account_id, definition_id=definition_id, value="independent"
                )
            )
            result = future.result(timeout=10)
            assert isinstance(result, CustomPropertyValue)
            assert result.value_str == "independent"
            assert self._event_values() == Counter(
                {_PropertyChange(previous_value=None, current_value="independent"): 1}
            )
        assert self._event_values() == Counter(
            {
                _PropertyChange(previous_value=None, current_value="first"): 1,
                _PropertyChange(previous_value=None, current_value="independent"): 1,
            }
        )

    @parameterized.expand([("set",), ("clear",), ("sync",), ("statement_timeout",)])
    def test_contention_preserves_the_error_type_and_restores_the_callers_timeout(self, operation: str) -> None:
        statement_timeout = operation == "statement_timeout"
        self.enterContext(patch(f"{_LOGIC}._CUSTOM_PROPERTY_VALUE_LOCK_TIMEOUT_MS", 30000 if statement_timeout else 50))

        def write() -> object:
            with transaction.atomic(using=self.using), connections[self.using].cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, true)", ["2s"])
                if statement_timeout:
                    cursor.execute("SELECT set_config('statement_timeout', %s, true)", ["50ms"])
                with self.assertRaises(OperationalError if statement_timeout else CustomPropertyValueConflict):
                    if operation == "clear":
                        self._clear()
                    elif operation == "sync":
                        self._sync("second")
                    else:
                        self._set("second")
                cursor.execute("SELECT current_setting('lock_timeout')")
                assert cursor.fetchone()[0] == "2s"
                assert not self._history()
            return True

        with transaction.atomic(using=self.using):
            with guard_custom_property_value(
                team_id=self.team.id,
                account_id=str(self.account.id).replace("-", "").upper(),
                definition_id=str(self.definition.id).upper(),
            ):
                pass
            assert self._start_writer(write).result(timeout=10) is True
        assert not self._history()
        assert not self.events.called
        assert self._set("retry").value_str == "retry"

    def test_successful_guard_restores_timeout_and_outer_rollback_discards_events(self) -> None:
        with transaction.atomic(using=self.using), connections[self.using].cursor() as cursor:
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", ["2s"])
            with guard_custom_property_value(
                team_id=self.team.id, account_id=self.account.id, definition_id=self.definition.id
            ):
                self._set("first")
                cursor.execute("SELECT current_setting('lock_timeout')")
                assert cursor.fetchone()[0] == "2s"
            assert not self.events.called
            transaction.set_rollback(True, using=self.using)
        assert not self._history()
        assert not self.events.called

    @parameterized.expand([("older", -1), ("within_interval", 1)])
    def test_slack_interval_check_reads_the_committed_value(self, _name: str, minutes: int) -> None:
        self.definition = CustomPropertyDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name=CANONICAL_LAST_SLACK_MESSAGE_AT, display_type=DisplayType.DATETIME
        )
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        with transaction.atomic(using=self.using):
            assert record_last_slack_message_at(team_id=self.team.id, account_id=self.account.id, timestamp=timestamp)
            future = self._start_writer(
                lambda: record_last_slack_message_at(
                    team_id=self.team.id,
                    account_id=self.account.id,
                    timestamp=timestamp + timedelta(minutes=minutes),
                )
            )
            self._wait_until_blocked(future)
        assert future.result(timeout=10) is False
        rows = (
            CustomPropertyValue.objects.for_team(self.team.id)
            .using(self.using)
            .filter(definition_id=self.definition.id)
        )
        assert rows.count() == 1
        assert rows.get().value_datetime == timestamp
        assert self._event_values() == Counter({_PropertyChange(previous_value=None, current_value=timestamp): 1})
