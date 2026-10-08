import uuid
from collections.abc import Callable
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

import dagster
import psycopg2
import psycopg2.extras
from confluent_kafka import KafkaError, KafkaException
from parameterized import parameterized

from posthog.dags.personhog_shadow_lane import (
    GROUP_ID_NOT_FOUND,
    NON_EMPTY_GROUP,
    SHADOW_KAFKA_BOOTSTRAP_ENV_VAR,
    ShadowLaneStartConfig,
    _reset_consumer_offsets,
    _reset_shadow_state,
    read_shadow_write_counter,
    require_shadow_dsn,
    shadow_kafka_admin,
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
        return SimpleNamespace(
            spec=SimpleNamespace(replicas=self.desired_replicas, selector=SimpleNamespace(match_labels={"app": name}))
        )


class _NoPodsCoreApi:
    def list_namespaced_pod(self, namespace: str, label_selector: str) -> SimpleNamespace:
        return SimpleNamespace(items=[])


@pytest.fixture
def stopped_lane(monkeypatch: pytest.MonkeyPatch) -> _FakeAppsApi:
    monkeypatch.setattr("posthog.dags.personhog_shadow_lane.k8s_client.CoreV1Api", _NoPodsCoreApi)
    return _FakeAppsApi(desired_replicas=0)


class _FakeKafkaAdmin:
    def __init__(self, error_code: int | None = None) -> None:
        self.error_code = error_code
        self.deleted: list[str] = []

    def delete_consumer_groups(self, group_ids: list[str], **_kwargs: object) -> dict[str, Future]:
        futures: dict[str, Future] = {}
        for group_id in group_ids:
            future: Future = Future()
            if self.error_code is None:
                self.deleted.append(group_id)
                future.set_result(None)
            else:
                future.set_exception(KafkaException(KafkaError(self.error_code)))
            futures[group_id] = future
        return futures


def _no_admin() -> _FakeKafkaAdmin:
    raise AssertionError("the admin client must not be reached while the lane has pods")


@parameterized.expand(
    [
        (
            "reset_state",
            lambda context, apps: _reset_shadow_state(context, ShadowLaneStartConfig(reset_state=True), apps),
        ),
        (
            "reset_offsets",
            lambda context, apps: _reset_consumer_offsets(
                context, ShadowLaneStartConfig(reset_offsets=True), apps, _no_admin
            ),
        ),
    ]
)
def test_reset_refuses_while_lane_wants_pods(
    _name: str, reset: Callable[[dagster.OpExecutionContext, _FakeAppsApi], object]
) -> None:
    with pytest.raises(dagster.Failure, match="stop-and-compare"):
        reset(dagster.build_op_context(), _FakeAppsApi(desired_replicas=2))


@pytest.mark.parametrize(
    "error_code,expected",
    [
        pytest.param(None, True, id="deleted"),
        pytest.param(GROUP_ID_NOT_FOUND, False, id="missing_group"),
    ],
)
def test_offset_reset_deletes_the_consumer_group(
    stopped_lane: _FakeAppsApi, error_code: int | None, expected: bool
) -> None:
    admin = _FakeKafkaAdmin(error_code)
    config = ShadowLaneStartConfig(reset_offsets=True, consumer_group="shadow-group")
    deleted = _reset_consumer_offsets(dagster.build_op_context(), config, stopped_lane, lambda: admin)
    assert deleted == expected
    assert admin.deleted == (["shadow-group"] if expected else [])


def test_offset_reset_fails_while_the_group_has_members(stopped_lane: _FakeAppsApi) -> None:
    admin = _FakeKafkaAdmin(NON_EMPTY_GROUP)
    with pytest.raises(dagster.Failure, match="still has members"):
        _reset_consumer_offsets(
            dagster.build_op_context(), ShadowLaneStartConfig(reset_offsets=True), stopped_lane, lambda: admin
        )


def test_offset_reset_needs_the_bootstrap_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SHADOW_KAFKA_BOOTSTRAP_ENV_VAR, raising=False)
    with pytest.raises(dagster.Failure, match=SHADOW_KAFKA_BOOTSTRAP_ENV_VAR):
        shadow_kafka_admin()


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
