import datetime as dt
from enum import auto
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from posthog.test.base import ClickhouseDestroyTablesMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.clickhouse.client import sync_execute
from posthog.models import OrganizationMembership, Team

from products.demo.backend.logic.matrix.manager import MatrixManager
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


class TestMatrixManagerKafkaBackpressure(SimpleTestCase):
    QUEUE_CAPACITY = 20

    def test_saves_more_events_than_the_producer_queue_holds(self):
        # A full librdkafka queue makes produce() raise BufferError instead of blocking,
        # so the loop has to drain the queue itself.
        queued: list[str] = []
        delivered: list[str] = []

        def fake_create_event(*, distinct_id, **kwargs):
            if len(queued) >= self.QUEUE_CAPACITY:
                raise BufferError("Local: Queue full")
            queued.append(distinct_id)

        def fake_flush_all_producers(timeout=None) -> int:
            delivered.extend(queued)
            queued.clear()
            return 0

        timestamp = dt.datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC"))
        events = [
            SimEvent(
                event="$pageview",
                distinct_id=f"person-{i}",
                properties={},
                timestamp=timestamp,
                person_id=uuid4(),
                person_properties={},
                person_created_at=timestamp,
            )
            for i in range(self.QUEUE_CAPACITY * 3)
        ]
        manager = MatrixManager(DummyMatrix(n_clusters=1))
        team = Team(id=1, project_id=1)

        with (
            patch("posthog.models.event.util.create_event", fake_create_event),
            patch("products.demo.backend.logic.matrix.manager.flush_all_producers", fake_flush_all_producers),
            patch("products.demo.backend.logic.matrix.manager.EVENTS_PER_KAFKA_FLUSH", self.QUEUE_CAPACITY // 2),
        ):
            manager._save_past_sim_events(team, events)
            manager._flush_kafka()

        assert delivered == [event.distinct_id for event in events]
