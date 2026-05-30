import datetime as dt
from enum import auto
from typing import Optional
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core import exceptions
from django.db import IntegrityError

from posthog.test.base import ClickhouseDestroyTablesMixin

from posthog.clickhouse.client import sync_execute
from posthog.demo.matrix.manager import MatrixManager
from posthog.demo.matrix.matrix import Cluster, Matrix
from posthog.demo.matrix.models import SimPerson, SimSessionIntent
from posthog.models import User


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

    def _make_collision_user(self, email: str) -> User:
        # bootstrap creates an organization, team, and user — needed so the existing user
        # has a current_team (the log-in branch asserts on it).
        _org, _team, user = User.objects.bootstrap(
            organization_name="Pre-existing org",
            email=email,
            password=None,
            first_name="Existing",
        )
        return user

    def test_ensure_account_logs_in_when_user_exists(self):
        email = "race-login@posthog.com"
        existing = self._make_collision_user(email)
        manager = MatrixManager(self.matrix)

        with patch.object(MatrixManager, "run_on_team"):
            _org, _team, user = manager.ensure_account_and_save(
                email, "Demo", "Demo Inc.", email_collision_handling="log_in"
            )

        assert user.pk == existing.pk

    def test_ensure_account_disambiguates_when_user_exists(self):
        email = "race-disambig@posthog.com"
        existing = self._make_collision_user(email)
        manager = MatrixManager(self.matrix)

        with patch.object(MatrixManager, "run_on_team"):
            _org, _team, user = manager.ensure_account_and_save(
                email, "Demo", "Demo Inc.", email_collision_handling="disambiguate"
            )

        assert user.pk != existing.pk
        assert user.email == "race-disambig+1@posthog.com"

    def test_ensure_account_retries_on_insert_race_in_disambiguate_mode(self):
        # Simulates the TOCTOU race: pre-check finds no user, but the INSERT fails because
        # the DB unique constraint fires (another process claimed the email in between).
        # The DB constraint is the source of truth, so the retry should pick a fresh suffix.
        email = "race-insert-disambig@posthog.com"
        manager = MatrixManager(self.matrix)
        call_state: dict[str, int] = {"count": 0}

        original_create_and_join = User.objects.create_and_join

        def racing_create_and_join(organization, candidate_email, *args, **kwargs):
            call_state["count"] += 1
            if call_state["count"] == 1:
                # First attempt: simulate the DB constraint raising despite a clean pre-check.
                raise IntegrityError(
                    "duplicate key value violates unique constraint posthog_user_email_af269794_uniq"
                )
            return original_create_and_join(organization, candidate_email, *args, **kwargs)

        with patch.object(MatrixManager, "run_on_team"), patch.object(
            User.objects, "create_and_join", side_effect=racing_create_and_join
        ):
            _org, _team, user = manager.ensure_account_and_save(
                email, "Demo", "Demo Inc.", email_collision_handling="disambiguate"
            )

        # The first attempt raised on `email`; the retry should land on the +1 suffix.
        assert call_state["count"] == 2
        assert user.email == "race-insert-disambig+1@posthog.com"

    def test_ensure_account_raises_for_staff_user_collision(self):
        email = "race-staff@posthog.com"
        existing = self._make_collision_user(email)
        existing.is_staff = True
        existing.save()
        manager = MatrixManager(self.matrix)

        with patch.object(MatrixManager, "run_on_team"):
            try:
                manager.ensure_account_and_save(
                    email, "Demo", "Demo Inc.", email_collision_handling="log_in"
                )
            except exceptions.PermissionDenied:
                pass
            else:
                raise AssertionError("Expected PermissionDenied for staff-user collision")
