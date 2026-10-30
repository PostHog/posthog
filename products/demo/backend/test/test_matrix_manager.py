import datetime as dt
from enum import auto
from typing import Any, Optional
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from posthog.test.base import ClickhouseDestroyTablesMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
from posthog.models import OrganizationMembership
from posthog.tasks.demo_create_data import copy_native_events_for_demo_team

from products.demo.backend.logic.matrix.manager import (
    QUEUE_FULL_MAX_FLUSHES,
    MatrixManager,
    _EventToSave,
    _produce_when_queue_has_room,
    _with_exposure_copies,
)
from products.demo.backend.logic.matrix.matrix import Cluster, Matrix
from products.demo.backend.logic.matrix.models import SimEvent, SimPerson, SimSessionIntent


class DummySessionIntent(SimSessionIntent):
    FLAIL = auto()


class DummyPerson(SimPerson):
    def determine_next_session_datetime(self):
        return self.cluster.start

    def determine_session_intent(self) -> Optional[DummySessionIntent]:
        return DummySessionIntent.FLAIL

    def simulate_session(self):
        self.active_client.capture_pageview(
            "/", {"foo": "bar", "optional": None, "nested": {"missing": None, "value": 1}}
        )
        self.active_client.identify(self.in_product_id)
        self.active_client.group("company", "Acme", {"bar": "foo"})
        self.active_client.capture(
            "$feature_flag_called", {"$feature_flag": "multivariate-flag", "$feature_flag_response": "test"}
        )
        self.active_client.capture(
            "$feature_flag_called", {"$feature_flag": "boolean-flag", "$feature_flag_response": "true"}
        )
        self.advance_timer(86400 * 12)


class DummyCluster(Cluster):
    MIN_RADIUS = 0
    MAX_RADIUS = 0

    def initiation_distribution(self) -> float:
        return 0  # Start every cluster at the same time


class DummyMatrix(Matrix):
    PRODUCT_NAME = "Test"
    CLUSTER_CLASS = DummyCluster
    PERSON_CLASS = DummyPerson

    def set_project_up(self, team, user):
        return super().set_project_up(team, user)


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
class TestMatrixManager(ClickhouseDestroyTablesMixin):
    CLASS_DATA_LEVEL_SETUP = False

    matrix: DummyMatrix

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.matrix = DummyMatrix(
            n_clusters=3,
            now=dt.datetime(2020, 1, 1, 0, 0, 0, 0, tzinfo=ZoneInfo("UTC")),
            days_future=0,
        )
        cls.matrix.simulate()

    def test_reset_master(self):
        manager = MatrixManager(self.matrix)

        manager.reset_master()

        # At least one event for each cluster
        assert sync_execute("SELECT count() FROM events WHERE team_id = 0")[0][0] >= 3

    def test_create_team(self):
        manager = MatrixManager(self.matrix)

        demo_team = manager.create_team(self.organization)

        assert demo_team.organization == self.organization
        assert demo_team.ingested_event
        assert demo_team.is_demo

    def test_ensure_account_creates_organization_owner(self):
        manager = MatrixManager(self.matrix)

        organization, _, user = manager.ensure_account_and_save("demo@example.com", "Demo", "Demo organization")

        membership = OrganizationMembership.objects.get(organization=organization, user=user)
        assert membership.level == OrganizationMembership.Level.OWNER

    def test_run_on_team(self):
        manager = MatrixManager(self.matrix)

        manager.run_on_team(self.team, self.user)

        # At least one event for each cluster
        assert (
            sync_execute(
                "SELECT count() FROM events WHERE team_id = %(team_id)s",
                {"team_id": self.team.pk},
            )[0][0]
            >= 3
        )
        assert self.team.name == DummyMatrix.PRODUCT_NAME
        exposures, multivariate_flag_calls = sync_execute(
            """
            SELECT
                countIf(event = '$experiment_exposure'),
                countIf(event = '$feature_flag_called' AND JSONExtractString(properties, '$feature_flag_response') = 'test')
            FROM events WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )[0]
        assert multivariate_flag_calls >= 3
        assert exposures == multivariate_flag_calls

    def test_run_on_team_marks_persons_that_identified(self):
        manager = MatrixManager(self.matrix)

        manager.run_on_team(self.team, self.user)

        assert (
            sync_execute(
                "SELECT countIf(is_identified = 1) FROM person WHERE team_id = %(team_id)s",
                {"team_id": self.team.pk},
            )[0][0]
            >= 3
        )

    @parameterized.expand(["copied", "unavailable", "copy_failed", "enqueue_failed", "ingestion_delayed"])
    def test_run_on_team_using_pre_save(self, native_result: str) -> None:
        manager = MatrixManager(self.matrix, use_pre_save=True)

        def execute_with_native_failure(query: str, *args: object, **kwargs: object) -> object:
            if "FROM events_json" in query:
                if native_result == "unavailable":
                    raise ConnectionError("Native event storage unavailable")
                if native_result == "ingestion_delayed":
                    return [(0,)]
            if native_result == "copy_failed" and query.lstrip().startswith("INSERT INTO events_json"):
                raise RuntimeError("Native event copy failed")
            return sync_execute(query, *args, **kwargs)

        with (
            patch("products.demo.backend.logic.matrix.manager.sync_execute", side_effect=execute_with_native_failure),
            patch("products.demo.backend.logic.matrix.manager.monotonic", side_effect=[0, 301]),
            patch.object(
                copy_native_events_for_demo_team, "apply_async", wraps=copy_native_events_for_demo_team.apply_async
            ) as enqueue,
            self.captureOnCommitCallbacks(execute=True),
        ):
            if native_result == "enqueue_failed":
                enqueue.side_effect = ConnectionError("Task queue unavailable")
            manager.run_on_team(self.team, self.user)
            assert self.team.name == DummyMatrix.PRODUCT_NAME
            copied = execute_hogql_query(
                "SELECT count() FROM events WHERE properties.foo = 'bar'",
                team=self.team,
                modifiers=HogQLQueryModifiers(useNewEventsSchema=False),
            )
            assert copied.results[0][0] >= 3
            assert (
                sync_execute("SELECT count() FROM events_json WHERE team_id = %(team_id)s", {"team_id": self.team.pk})[
                    0
                ][0]
                == 0
            )

        # The copy retains event payloads and identities, while the new insert gets its own ingestion metadata.
        for read_table in ("events", "events_json", "groups"):
            rows = sync_execute(
                f"""
                SELECT team_id, toJSONString(tuple(* EXCEPT (
                    team_id, _timestamp, _offset, _partition, inserted_at, consumer_breadcrumbs, historical_migration
                )))
                FROM {read_table} WHERE team_id IN (0, %(team_id)s) ORDER BY 2
                """,
                {"team_id": self.team.pk},
            )
            source = [row for team_id, row in rows if team_id == 0]
            target = [row for team_id, row in rows if team_id == self.team.pk]
            assert source
            if read_table == "events_json" and native_result != "copied":
                assert target == []
            else:
                assert target == source

        if native_result == "copied":
            copied = execute_hogql_query(
                "SELECT count() FROM events WHERE properties.foo = 'bar'",
                team=self.team,
                modifiers=HogQLQueryModifiers(useNewEventsSchema=True),
            )
            assert copied.results[0][0] >= 3


class TestWithExposureCopies(SimpleTestCase):
    @parameterized.expand(
        [
            ("multivariate_response", "$feature_flag_called", "test", True),
            ("true_string_response", "$feature_flag_called", "true", False),
            ("false_string_response", "$feature_flag_called", "false", False),
            ("empty_string_response", "$feature_flag_called", "", False),
            ("boolean_response", "$feature_flag_called", True, False),
            ("other_event_with_variant", "$pageview", "test", False),
        ]
    )
    def test_copies_only_multivariate_flag_calls(
        self, _name: str, event_name: str, response: Any, expect_copy: bool
    ) -> None:
        timestamp = dt.datetime(2020, 1, 1, tzinfo=ZoneInfo("UTC"))
        event = SimEvent(
            event=event_name,
            distinct_id="person-1",
            properties={"$feature_flag": "some-flag", "$feature_flag_response": response},
            timestamp=timestamp,
            person_id=uuid4(),
            person_properties={},
            person_created_at=timestamp,
        )

        saved = list(_with_exposure_copies([event]))

        source_uuid = saved[0].uuid
        expected = [_EventToSave(uuid=source_uuid, name=event_name, source=event)]
        if expect_copy:
            ingestion_namespace = UUID("1b7c9119-5953-4668-97b7-ab0ef8a6bb48")
            expected.append(
                _EventToSave(
                    uuid=uuid5(ingestion_namespace, str(source_uuid)), name="$experiment_exposure", source=event
                )
            )
        assert saved == expected


class TestProduceWhenQueueHasRoom(SimpleTestCase):
    @parameterized.expand(
        [
            ("room_on_first_try", 0, 0),
            ("queue_drains_after_flushes", 3, 3),
            ("queue_drains_on_last_attempt", QUEUE_FULL_MAX_FLUSHES, QUEUE_FULL_MAX_FLUSHES),
        ]
    )
    @patch("products.demo.backend.logic.matrix.manager.get_producer")
    def test_retries_until_the_queue_has_room(
        self, _name: str, buffer_errors: int, expected_flushes: int, mock_get_producer: MagicMock
    ) -> None:
        produce = MagicMock(side_effect=[BufferError("Local: Queue full")] * buffer_errors + [None])

        _produce_when_queue_has_room(produce)

        self.assertEqual(produce.call_count, buffer_errors + 1)
        self.assertEqual(mock_get_producer.return_value.flush.call_count, expected_flushes)

    @patch("products.demo.backend.logic.matrix.manager.get_producer")
    def test_raises_when_the_queue_stays_full(self, mock_get_producer: MagicMock) -> None:
        produce = MagicMock(side_effect=BufferError("Local: Queue full"))

        with self.assertRaises(BufferError):
            _produce_when_queue_has_room(produce)

        self.assertEqual(produce.call_count, QUEUE_FULL_MAX_FLUSHES + 1)
        self.assertEqual(mock_get_producer.return_value.flush.call_count, QUEUE_FULL_MAX_FLUSHES)
        mock_get_producer.assert_called_with(topic=KAFKA_EVENTS_JSON)
        mock_get_producer.return_value.flush.assert_called_with(timeout=1.0)
