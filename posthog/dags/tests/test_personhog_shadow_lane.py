import uuid
from types import SimpleNamespace

import pytest

import dagster
import psycopg2
import psycopg2.extras
from parameterized import parameterized

from posthog.dags.personhog_shadow_lane import (
    ShadowLaneStartConfig,
    _reset_shadow_state,
    read_shadow_write_counter,
    require_shadow_dsn,
    wait_for_deployments,
    wait_for_quiescence,
)
from posthog.persons_db import persons_db_url


class TestRequireShadowDsn:
    @parameterized.expand(
        [
            ("postgres://user:pass@persons-shadow.cluster-abc.us-east-1.rds.amazonaws.com:5432/posthog",),
            ("postgres://user@localhost:5432/persons_shadow_test",),
        ]
    )
    def test_accepts_shadow_targets(self, url: str) -> None:
        require_shadow_dsn(url)

    @parameterized.expand(
        [
            (
                "postgres://user:pass@posthog-cloud-persons-prod-us-east-1.cluster-abc.us-east-1.rds.amazonaws.com:5432/posthog",
            ),
            ("postgres://user@localhost:5432/posthog_persons",),
            ("postgres://user:shadow@localhost:5432/posthog_persons",),
            # libpq lets query parameters and multi-host authorities point the
            # connection somewhere other than the URL's hostname.
            ("postgres://user@persons-shadow.example:5432/posthog?hostaddr=10.0.0.1",),
            ("postgres://user@persons-shadow.example:5432/posthog?host=prod.example",),
            ("postgres://user@persons-shadow.example:5432/posthog?dbname=production",),
            ("postgres://user@persons-shadow.example:5432/posthog?service=prod",),
            ("postgres://user@persons-shadow.example,prod.example:5432/posthog",),
            # A libpq key/value DSN has no URL authority for the guard to check.
            ("host=prod.example dbname=posthog user=dagster_shadow",),
        ]
    )
    def test_rejects_non_shadow_targets(self, url: str) -> None:
        with pytest.raises(dagster.Failure):
            require_shadow_dsn(url)


class TestWaitForQuiescence:
    @parameterized.expand(
        [
            ("flat_counter", [5, 5, 5, 5], 3, 4),
            ("moving_then_flat", [5, 6, 6, 7, 7, 7], 2, 6),
        ]
    )
    def test_returns_once_counter_is_stable(
        self, _name: str, readings: list[int], stable_checks: int, expected_polls: int
    ) -> None:
        values = iter(readings)
        polls = wait_for_quiescence(
            lambda: next(values),
            poll_seconds=0,
            stable_checks=stable_checks,
            timeout_seconds=60,
            sleep=lambda _seconds: None,
        )
        assert polls == expected_polls

    def test_raises_when_counter_never_settles(self) -> None:
        counter = iter(range(1000))
        with pytest.raises(TimeoutError):
            wait_for_quiescence(
                lambda: next(counter),
                poll_seconds=0,
                stable_checks=2,
                timeout_seconds=0,
                sleep=lambda _seconds: None,
            )


class TestWaitForDeployments:
    @parameterized.expand(
        [
            ("all_settle", {"consumer": 2, "processor": 1}, 60, set()),
            ("deadline_passed", {"consumer": 0, "processor": 0}, 0, {"consumer", "processor"}),
        ]
    )
    def test_returns_what_is_still_pending(
        self, _name: str, settles_on_check: dict[str, int], timeout_seconds: int, expected_pending: set[str]
    ) -> None:
        checks: dict[str, int] = dict.fromkeys(settles_on_check, 0)

        def is_settled(deployment: str) -> bool:
            checks[deployment] += 1
            return 0 < settles_on_check[deployment] <= checks[deployment]

        pending = wait_for_deployments(
            settles_on_check, is_settled, timeout_seconds=timeout_seconds, sleep=lambda _seconds: None
        )
        assert pending == expected_pending


class _FakeAppsApi:
    def __init__(self, desired_replicas: int) -> None:
        self.desired_replicas = desired_replicas

    def read_namespaced_deployment(self, name: str, namespace: str) -> SimpleNamespace:
        return SimpleNamespace(spec=SimpleNamespace(replicas=self.desired_replicas))


def test_reset_refuses_while_lane_wants_pods() -> None:
    context = dagster.build_op_context()
    with pytest.raises(dagster.Failure, match="stop-and-compare"):
        _reset_shadow_state(context, ShadowLaneStartConfig(reset_state=True), _FakeAppsApi(desired_replicas=2))


@pytest.mark.persons_db_direct
@pytest.mark.django_db(transaction=True)
def test_write_counter_ignores_lifecycle_op_tables() -> None:
    connection = psycopg2.connect(persons_db_url(writer=True), cursor_factory=psycopg2.extras.RealDictCursor)
    connection.autocommit = True
    op_id = str(uuid.uuid4())
    person_uuid = str(uuid.uuid4())
    try:
        before = read_shadow_write_counter(connection)

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO lifecycle_op_tmp (op_id, op_type, team_id, step, request) "
                "VALUES (%s, 'merge', 2, 'start', '{}')",
                (op_id,),
            )
            cursor.execute("DELETE FROM lifecycle_op_tmp WHERE op_id = %s", (op_id,))
            cursor.execute("SELECT pg_stat_force_next_flush()")
        assert read_shadow_write_counter(connection) == before

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO posthog_person (created_at, properties, is_identified, uuid, version, team_id, is_deleted) "
                "VALUES (now(), '{}', false, %s, 1, 2, false)",
                (person_uuid,),
            )
            cursor.execute("SELECT pg_stat_force_next_flush()")
        assert read_shadow_write_counter(connection) == before + 1
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM posthog_person WHERE uuid = %s", (person_uuid,))
        connection.close()
