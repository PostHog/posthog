import datetime as dt
from enum import auto
from typing import Optional
from zoneinfo import ZoneInfo

from posthog.test.base import ClickhouseDestroyTablesMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
from posthog.models import OrganizationMembership

from products.demo.backend.logic.matrix.manager import (
    QUEUE_FULL_MAX_FLUSHES,
    MatrixManager,
    _produce_when_queue_has_room,
)
from products.demo.backend.logic.matrix.matrix import Cluster, Matrix
from products.demo.backend.logic.matrix.models import SimPerson, SimSessionIntent


class DummySessionIntent(SimSessionIntent):
    FLAIL = auto()


class DummyPerson(SimPerson):
    def determine_next_session_datetime(self):
        return self.cluster.start

    def determine_session_intent(self) -> Optional[DummySessionIntent]:
        return DummySessionIntent.FLAIL

    def simulate_session(self):
        self.active_client.capture_pageview("/", {"foo": "bar"})
        self.active_client.identify(self.in_product_id)
        self.active_client.group("company", "Acme", {"bar": "foo"})
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

    def test_run_on_team_using_pre_save(self):
        manager = MatrixManager(self.matrix, use_pre_save=True)

        manager.run_on_team(self.team, self.user)

        # At least one event for each cluster
        assert sync_execute("SELECT count() FROM events WHERE team_id = 0")[0][0] >= 3
        assert (
            sync_execute(
                "SELECT count() FROM events WHERE team_id = %(team_id)s",
                {"team_id": self.team.pk},
            )[0][0]
            >= 3
        )


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
