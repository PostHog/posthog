import time
import itertools
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

import pytest
from unittest.mock import patch

import grpc
import dagster
import psycopg2
from prometheus_client import CollectorRegistry

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags import person_pg_cleanup_drain as drain
from posthog.dags.clickhouse_cleanup import PG_CLEANUP_QUEUE_TABLE
from posthog.dags.person_pg_cleanup_drain import (
    Chunk,
    DrainTotals,
    QueueRow,
    backoff_seconds,
    chunks_for_page,
    person_pg_cleanup_drain_job,
    pg_recovery,
)
from posthog.personhog_client.fake_client import FakePersonHogClient, get_active_fake
from posthog.personhog_client.proto import (
    DeleteTombstonedPersonsRequest,
    DeleteTombstonedPersonsResponse,
    GetPersonByUuidRequest,
)
from posthog.persons_db import persons_db_url

TEAM_A = 4242
TEAM_B = 4343
# Sweep timestamps are only ever compared with each other, never with the clock.
SWEEP_1 = datetime(2026, 1, 1, tzinfo=UTC)
SWEEP_2 = datetime(2026, 1, 8, tzinfo=UTC)
OP = "drain_person_pg_cleanup_queue"

# Pacing and backoff are zeroed so the suite never sleeps.
FAST = {"pause_ms": 0, "latency_multiplier": 0.0, "retry_backoff_seconds": 0.0}


def queue(conn, rows: list[tuple[int, str, datetime]]) -> None:
    with conn.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO {PG_CLEANUP_QUEUE_TABLE} (team_id, person_uuid, deleted_at) VALUES (%s, %s, %s)", rows
        )
    conn.commit()


def queued(conn) -> list[tuple[int, str, datetime, datetime | None]]:
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT team_id, person_uuid::text, deleted_at, blocked_at FROM {PG_CLEANUP_QUEUE_TABLE} ORDER BY 1, 2"
        )
        return cursor.fetchall()


def run_job(cluster: ClickhouseCluster, *, dry_run: bool = False, raise_on_error: bool = True, **overrides):
    config = {"dry_run": dry_run, **FAST, **overrides}
    return person_pg_cleanup_drain_job.execute_in_process(
        run_config={"ops": {OP: {"config": config}}},
        resources={"cluster": cluster, "persons_database_url": persons_db_url(writer=True)},
        raise_on_error=raise_on_error,
    )


def totals_of(result: dagster.ExecuteInProcessResult) -> DrainTotals:
    return result.output_for_node(OP)


def failure_of(result: dagster.ExecuteInProcessResult) -> tuple[str, Mapping[str, dagster.MetadataValue]]:
    failure = result.failure_data_for_node(OP)
    assert failure is not None and failure.user_failure_data is not None
    return failure.user_failure_data.description or "", failure.user_failure_data.metadata


def seed_tombstoned(fake: FakePersonHogClient, team_id: int, person_id: int) -> str:
    uuid = str(uuid4())
    distinct_ids = [f"{person_id}-a", f"{person_id}-b"]
    fake.add_person(
        team_id=team_id,
        person_id=person_id,
        uuid=uuid,
        distinct_ids=distinct_ids,
        is_deleted=True,
        tombstoned_distinct_ids=distinct_ids,
    )
    return uuid


def seed_live(fake: FakePersonHogClient, team_id: int, person_id: int) -> str:
    uuid = str(uuid4())
    fake.add_person(team_id=team_id, person_id=person_id, uuid=uuid, distinct_ids=[f"{person_id}-a"])
    return uuid


def seed_blocked(fake: FakePersonHogClient, team_id: int, person_id: int) -> str:
    uuid = str(uuid4())
    fake.add_person(
        team_id=team_id,
        person_id=person_id,
        uuid=uuid,
        distinct_ids=[f"{person_id}-a", f"{person_id}-live"],
        is_deleted=True,
        tombstoned_distinct_ids=[f"{person_id}-a"],
    )
    return uuid


def seed_big(fake: FakePersonHogClient, team_id: int, person_id: int, distinct_ids: int = 5, live: int = 0) -> str:
    # Over the fake's row budget of two per request, which stands in for the replica's
    # TOMBSTONED_DELETE_MAX_ROWS clamp; the first `live` distinct ids stay live.
    uuid = str(uuid4())
    fake.tombstoned_delete_max_rows = 2
    ids = [f"{person_id}-{i}" for i in range(distinct_ids)]
    fake.add_person(
        team_id=team_id,
        person_id=person_id,
        uuid=uuid,
        distinct_ids=ids,
        is_deleted=True,
        tombstoned_distinct_ids=ids[live:],
    )
    return uuid


def present(fake: FakePersonHogClient, team_id: int, uuid: str) -> bool:
    return fake.get_person_by_uuid(GetPersonByUuidRequest(team_id=team_id, uuid=uuid)).HasField("person")


def delete_requests(fake: FakePersonHogClient) -> list:
    return [call.request for call in fake.calls if call.method == "delete_tombstoned_persons"]


def distinct_id_count(fake: FakePersonHogClient, team_id: int, uuid: str) -> int:
    person = fake.get_person_by_uuid(GetPersonByUuidRequest(team_id=team_id, uuid=uuid)).person
    return len(fake._distinct_ids.get((team_id, person.id), []))


class _RpcError(grpc.RpcError):
    def __init__(self, code: grpc.StatusCode) -> None:
        super().__init__()
        self._code = code

    def code(self) -> grpc.StatusCode:
        return self._code


def fail_with(monkeypatch: pytest.MonkeyPatch, fake: FakePersonHogClient, codes: list[grpc.StatusCode]) -> None:
    # The first len(codes) requests raise the given status before reaching the fake; later ones
    # reach it.
    pending = list(codes)
    original = fake.delete_tombstoned_persons

    def wrapped(
        request: DeleteTombstonedPersonsRequest, timeout: float | None = None
    ) -> DeleteTombstonedPersonsResponse:
        if pending:
            raise _RpcError(pending.pop(0))
        return original(request, timeout=timeout)

    monkeypatch.setattr(fake, "delete_tombstoned_persons", wrapped)


def record_emits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, str]]]:
    emitted: list[tuple[str, dict[str, str]]] = []

    def recorder(metrics: MetricsClient, name: str, labels: Mapping[str, str], value: float = 1.0) -> None:
        emitted.append((name, dict(labels)))

    monkeypatch.setattr(drain, "_emit", recorder)
    return emitted


def record_pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    pauses: list[float] = []
    monkeypatch.setattr(drain, "_pause", pauses.append)
    return pauses


def _pg_error(pgcode: str | None) -> psycopg2.Error:
    # pgcode is a read-only attribute on psycopg2.Error, so a subclass attribute stands in for it.
    return type("_PgError", (psycopg2.Error,), {"pgcode": pgcode})()


@pytest.mark.django_db
def test_deletes_tombstoned_persons_and_removes_their_queue_rows(cluster: ClickhouseCluster, persons_database):
    fake = get_active_fake()
    a1 = seed_tombstoned(fake, TEAM_A, 1)
    a2 = seed_tombstoned(fake, TEAM_A, 2)
    b1 = seed_tombstoned(fake, TEAM_B, 3)
    queue(persons_database, [(TEAM_A, a1, SWEEP_1), (TEAM_A, a2, SWEEP_1), (TEAM_B, b1, SWEEP_1)])

    result = run_job(cluster)

    assert result.success
    assert not present(fake, TEAM_A, a1) and not present(fake, TEAM_A, a2) and not present(fake, TEAM_B, b1)
    assert queued(persons_database) == []
    requests = delete_requests(fake)
    assert sorted(request.team_id for request in requests) == [TEAM_A, TEAM_B]
    assert {uuid for request in requests for uuid in request.person_uuids} == {a1, a2, b1}
    assert all(request.max_rows == drain.STEP_START_ROWS for request in requests)
    totals = totals_of(result)
    assert (totals.persons_deleted, totals.rows_deleted, totals.queue_rows_deleted) == (3, 6, 3)
    assert (totals.requests_pending_resent, totals.stopped_reason) == (0, "drained")
    assert result.output_for_node("publish_drain_metrics") == totals


@pytest.mark.django_db
def test_removes_rows_for_live_and_unknown_persons_without_deleting_them(cluster: ClickhouseCluster, persons_database):
    # A live row means Postgres revived the person after the sweep queued it; an unknown row means
    # another path already hard-deleted it. Both rows must go, or they are re-sent every run.
    fake = get_active_fake()
    live = seed_live(fake, TEAM_A, 1)
    gone = seed_tombstoned(fake, TEAM_A, 2)
    unknown = str(uuid4())
    queue(persons_database, [(TEAM_A, live, SWEEP_1), (TEAM_A, gone, SWEEP_1), (TEAM_A, unknown, SWEEP_1)])

    result = run_job(cluster)

    assert queued(persons_database) == []
    assert present(fake, TEAM_A, live)
    totals = totals_of(result)
    assert (totals.persons_deleted, totals.persons_skipped_live, totals.persons_not_found) == (1, 1, 1)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "seed,distinct_ids_kept,resends",
    [(seed_blocked, 2, 0), (partial(seed_big, live=1), 5, 1)],
)
def test_blocked_rows_stay_queued_and_are_skipped_inside_the_retry_window(
    cluster: ClickhouseCluster, persons_database, seed, distinct_ids_kept, resends
):
    # personhog reports a tombstoned person that still owns a live distinct id, whether the person
    # fits a request or is read in a trim step on the re-send. The row must survive with blocked_at
    # set and nothing of the person deleted.
    fake = get_active_fake()
    blocked = seed(fake, TEAM_A, 1)
    gone = seed_tombstoned(fake, TEAM_A, 2)
    queue(persons_database, [(TEAM_A, blocked, SWEEP_1), (TEAM_A, gone, SWEEP_1)])

    first = run_job(cluster)

    [(team_id, person_uuid, _, blocked_at)] = queued(persons_database)
    assert (team_id, person_uuid) == (TEAM_A, blocked)
    assert blocked_at is not None
    assert present(fake, TEAM_A, blocked) and not present(fake, TEAM_A, gone)
    assert distinct_id_count(fake, TEAM_A, blocked) == distinct_ids_kept
    totals = totals_of(first)
    assert (totals.persons_blocked, totals.blocked_sample, totals.requests_pending_resent) == (1, [blocked], resends)

    second = run_job(cluster)
    assert totals_of(second).rows_read == 0, "a freshly blocked row is skipped inside the retry window"

    third = run_job(cluster, blocked_retry_hours=0)
    assert totals_of(third).persons_blocked == 1, "past the window the row is retried and reported again"


@pytest.mark.django_db
def test_a_person_over_the_budget_is_finished_across_pending_resends_and_small_persons_never_wait(
    cluster: ClickhouseCluster, persons_database
):
    # The 5-row person comes back pending until what is left of it fits a request; the 2-row
    # person in the same request is deleted by the first call and never waits for it.
    fake = get_active_fake()
    big = seed_big(fake, TEAM_A, 1, distinct_ids=5)
    small = seed_tombstoned(fake, TEAM_A, 2)
    queue(persons_database, [(TEAM_A, big, SWEEP_1), (TEAM_A, small, SWEEP_1)])

    result = run_job(cluster)

    totals = totals_of(result)
    assert queued(persons_database) == []
    assert not present(fake, TEAM_A, big) and not present(fake, TEAM_A, small)
    # Call 1 deletes the small person and leaves the budget spent; calls 2 and 3 trim two rows
    # each; call 4 finds one row left, which fits, and deletes the person whole.
    assert [sorted(request.person_uuids) for request in delete_requests(fake)] == [sorted([big, small]), [big]] + [
        [big]
    ] * 2
    assert (totals.rpc_calls, totals.requests_pending_resent, totals.rows_deleted, totals.persons_deleted) == (
        4,
        3,
        7,
        2,
    )
    assert (totals.rows_stamped_blocked, totals.rpc_errors) == (0, 0)


@pytest.mark.django_db
def test_pending_resends_stop_at_max_runtime_and_the_next_run_continues(
    cluster: ClickhouseCluster, persons_database, monkeypatch
):
    # Rows deleted by the calls already made stay deleted; the queue row stays put and unstamped,
    # and the next run picks the person up where it stands.
    fake = get_active_fake()
    big = seed_big(fake, TEAM_A, 1, distinct_ids=5)
    queue(persons_database, [(TEAM_A, big, SWEEP_1)])
    # The clock is read at start, before the page and before the first request; the read before
    # the pending re-send is past the deadline.
    clock = itertools.chain([0.0] * 3, itertools.repeat(10**9))
    monkeypatch.setattr(drain, "_now_monotonic", lambda: next(clock))

    first = run_job(cluster)

    totals = totals_of(first)
    assert (totals.stopped_reason, totals.rpc_calls, totals.rows_deleted) == ("max_runtime", 1, 2)
    assert queued(persons_database) == [(TEAM_A, big, SWEEP_1, None)]
    assert distinct_id_count(fake, TEAM_A, big) == 3

    second = run_job(cluster)

    assert queued(persons_database) == []
    assert not present(fake, TEAM_A, big)
    assert (totals_of(second).rpc_calls, totals_of(second).requests_pending_resent) == (2, 1)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "code,step_after_failure",
    [
        (grpc.StatusCode.DEADLINE_EXCEEDED, 200),
        (grpc.StatusCode.UNAVAILABLE, 200),
        (grpc.StatusCode.INTERNAL, 400),
    ],
)
def test_the_step_halves_after_a_timeout_and_doubles_after_a_run_of_successes(
    cluster: ClickhouseCluster, persons_database, monkeypatch, code, step_after_failure
):
    # A timeout halves the 400-row step to 200 before the retry; twenty successes in a row double
    # it back, capped at max_rows_per_request. Other errors leave it alone, and nothing is stamped.
    fake = get_active_fake()
    uuids = [seed_tombstoned(fake, TEAM_A, person_id) for person_id in range(1, 26)]
    queue(persons_database, [(TEAM_A, uuid, SWEEP_1) for uuid in uuids])
    fail_with(monkeypatch, fake, [code])

    result = run_job(cluster, rpc_batch_size=1, max_rows_per_request=400)

    assert [request.max_rows for request in delete_requests(fake)] == [step_after_failure] * 20 + [400] * 5
    totals = totals_of(result)
    assert (totals.rpc_calls, totals.rpc_errors, totals.step_rows_min, totals.step_rows_max) == (
        25,
        1,
        step_after_failure,
        400,
    )
    assert queued(persons_database) == []
    assert totals.rows_stamped_blocked == 0


@pytest.mark.django_db
def test_too_many_blocked_rows_fail_the_run(cluster: ClickhouseCluster, persons_database):
    fake = get_active_fake()
    blocked = seed_blocked(fake, TEAM_A, 1)
    queue(persons_database, [(TEAM_A, blocked, SWEEP_1)])

    result = run_job(cluster, max_blocked=0, raise_on_error=False)

    assert not result.success
    [(_, _, _, blocked_at)] = queued(persons_database)
    assert blocked_at is not None, "the row is stamped before the run gives up, so operators can find it"
    assert present(fake, TEAM_A, blocked)
    description, _ = failure_of(result)
    assert "max_blocked" in description


@pytest.mark.django_db
def test_dry_run_counts_the_queue_without_calling_personhog_or_writing(
    cluster: ClickhouseCluster, persons_database, monkeypatch
):
    fake = get_active_fake()
    gone = seed_tombstoned(fake, TEAM_A, 1)
    queue(persons_database, [(TEAM_A, gone, SWEEP_1), (TEAM_B, str(uuid4()), SWEEP_2)])
    monkeypatch.setattr(drain, "require_personhog_client", lambda: (_ for _ in ()).throw(RuntimeError("no client")))

    result = run_job(cluster, dry_run=True)

    assert result.success
    assert delete_requests(fake) == []
    assert len(queued(persons_database)) == 2
    assert present(fake, TEAM_A, gone)
    totals = totals_of(result)
    assert (totals.rows_read, totals.teams_touched, totals.rpc_calls) == (2, {TEAM_A, TEAM_B}, 0)


@pytest.mark.django_db
def test_every_row_is_drained_exactly_once_across_page_and_chunk_boundaries(
    cluster: ClickhouseCluster, persons_database
):
    # Pages of two and requests of one put boundaries everywhere: an off-by-one at a page edge, a
    # stop after a full final page, or a lost chunk would leave a row queued or send one twice.
    fake = get_active_fake()
    uuids = [seed_tombstoned(fake, TEAM_A, person_id) for person_id in range(1, 6)]
    uuids.append(seed_tombstoned(fake, TEAM_B, 6))
    queue(persons_database, [(TEAM_A, uuid, SWEEP_1) for uuid in uuids[:5]] + [(TEAM_B, uuids[5], SWEEP_1)])

    result = run_job(cluster, page_size=2, rpc_batch_size=1)

    sent = [uuid for request in delete_requests(fake) for uuid in request.person_uuids]
    assert sorted(sent) == sorted(uuids)
    assert all(len(request.person_uuids) == 1 for request in delete_requests(fake))
    assert queued(persons_database) == []
    assert totals_of(result).pages == 3


@pytest.mark.django_db
def test_max_persons_caps_the_run_and_the_next_run_finishes_the_rest(cluster: ClickhouseCluster, persons_database):
    fake = get_active_fake()
    uuids = [seed_tombstoned(fake, TEAM_A, person_id) for person_id in range(1, 6)]
    queue(persons_database, [(TEAM_A, uuid, SWEEP_1) for uuid in uuids])

    capped = run_job(cluster, max_persons=2, page_size=1000)

    assert totals_of(capped).stopped_reason == "max_persons"
    assert totals_of(capped).persons_deleted == 2
    assert len(queued(persons_database)) == 3

    rest = run_job(cluster)

    assert totals_of(rest).persons_deleted == 3
    assert queued(persons_database) == []


@pytest.mark.django_db
def test_rows_from_two_sweeps_are_sent_separately_and_a_requeued_row_survives(
    cluster: ClickhouseCluster, persons_database, monkeypatch
):
    # Rows of one team from two sweep runs travel in separate requests so the queue delete can pin
    # deleted_at. A row the sweep re-queues mid-flight keeps the newer deleted_at and is drained
    # next run instead of being deleted on stale evidence.
    fake = get_active_fake()
    old = seed_tombstoned(fake, TEAM_A, 1)
    new = seed_tombstoned(fake, TEAM_A, 2)
    requeued = seed_tombstoned(fake, TEAM_A, 3)
    requeued_blocked = seed_blocked(fake, TEAM_A, 4)
    queue(
        persons_database,
        [
            (TEAM_A, old, SWEEP_1),
            (TEAM_A, requeued, SWEEP_1),
            (TEAM_A, requeued_blocked, SWEEP_1),
            (TEAM_A, new, SWEEP_2),
        ],
    )
    original = fake.delete_tombstoned_persons

    def requeue_during_rpc(
        request: DeleteTombstonedPersonsRequest, timeout: float | None = None
    ) -> DeleteTombstonedPersonsResponse:
        if requeued in request.person_uuids:
            with persons_database.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {PG_CLEANUP_QUEUE_TABLE} SET deleted_at = %s WHERE person_uuid = ANY(%s::uuid[])",
                    (SWEEP_2, [requeued, requeued_blocked]),
                )
            persons_database.commit()
        return original(request, timeout=timeout)

    monkeypatch.setattr(fake, "delete_tombstoned_persons", requeue_during_rpc)

    result = run_job(cluster)

    sent = [sorted(request.person_uuids) for request in delete_requests(fake)]
    assert sorted(sent) == sorted([sorted([old, requeued, requeued_blocked]), [new]])
    # Both re-queued rows survive untouched: the resolved one is not deleted, and the blocked one is
    # not stamped, because both now belong to the newer sweep.
    assert queued(persons_database) == sorted(
        [(TEAM_A, requeued, SWEEP_2, None), (TEAM_A, requeued_blocked, SWEEP_2, None)], key=lambda row: row[1]
    )
    assert totals_of(result).queue_rows_deleted == 2
    # The stamp the guard refused must not count toward max_blocked either.
    assert (totals_of(result).rows_stamped_blocked, totals_of(result).blocked_sample) == (0, [])


@pytest.mark.django_db
@pytest.mark.parametrize(
    "codes,window,expect_success",
    [
        ([grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.INTERNAL, grpc.StatusCode.UNAVAILABLE], 900.0, True),
        ([grpc.StatusCode.UNAVAILABLE] * 50, 0.0, False),
    ],
)
def test_rpc_failures_are_retried_inside_the_window_and_fail_the_run_after_it(
    cluster: ClickhouseCluster, persons_database, monkeypatch, codes, window, expect_success
):
    # Inside the window every failure is retried whatever its code; past it the run fails with the
    # request in the failure, its rows in place and nothing stamped, so a rerun finishes the work.
    fake = get_active_fake()
    gone = seed_tombstoned(fake, TEAM_A, 1)
    queue(persons_database, [(TEAM_A, gone, SWEEP_1)])
    fail_with(monkeypatch, fake, codes)
    emitted = record_emits(monkeypatch)

    result = run_job(cluster, rpc_retry_window_seconds=window, raise_on_error=False)

    assert result.success is expect_success
    if expect_success:
        assert queued(persons_database) == []
        assert (totals_of(result).rpc_errors, totals_of(result).rpc_calls) == (len(codes), 1)
        return
    assert queued(persons_database) == [(TEAM_A, gone, SWEEP_1, None)]
    assert present(fake, TEAM_A, gone)
    description, metadata = failure_of(result)
    assert "stay queued for the next run" in description
    assert (metadata["team_id"].value, metadata["first_uuid"].value, metadata["sent_size"].value) == (TEAM_A, gone, 1)
    assert (metadata["attempts"].value, metadata["grpc_code"].value) == (1, "UNAVAILABLE")
    assert metadata["rows_stamped_blocked"].value == 0
    # A failed run still reports what it did, or dashboards see a silent gap instead of a failure.
    assert ("person_pg_cleanup_drain_runs", {"stopped_reason": "failed", "dry_run": "false"}) in emitted
    assert ("person_pg_cleanup_drain_rpc_calls", {"result": "error", "code": "UNAVAILABLE"}) in emitted


@pytest.mark.django_db
@pytest.mark.parametrize(
    "code", [grpc.StatusCode.UNIMPLEMENTED, grpc.StatusCode.INVALID_ARGUMENT, grpc.StatusCode.PERMISSION_DENIED]
)
def test_a_fatal_rpc_code_fails_immediately_without_retrying_or_writing(
    cluster: ClickhouseCluster, persons_database, monkeypatch, code
):
    # An older personhog answers UNIMPLEMENTED, and a wrong or unauthorized request gets the same
    # answer every time. The legacy delete RPC has no tombstone check, so the run must stop rather
    # than fall back to it.
    fake = get_active_fake()
    uuids = [seed_tombstoned(fake, TEAM_A, person_id) for person_id in range(1, 3)]
    queue(persons_database, [(TEAM_A, uuid, SWEEP_1) for uuid in uuids])
    fail_with(monkeypatch, fake, [code] * 5)

    result = run_job(cluster, raise_on_error=False)

    assert not result.success
    assert len(delete_requests(fake)) == 0, "the wrapper raised before the fake recorded a call"
    assert queued(persons_database) == sorted((TEAM_A, uuid, SWEEP_1, None) for uuid in uuids)
    assert all(present(fake, TEAM_A, uuid) for uuid in uuids)
    _, metadata = failure_of(result)
    assert metadata["rpc_errors"].value == 1, "one attempt and no retry"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides,expected_deleted,stopped_reason",
    [({}, 1, "max_runtime"), ({"max_runtime_seconds": 0}, 3, "drained")],
)
def test_max_runtime_stops_between_pages_unless_disabled(
    cluster: ClickhouseCluster, persons_database, monkeypatch, overrides, expected_deleted, stopped_reason
):
    fake = get_active_fake()
    uuids = [seed_tombstoned(fake, TEAM_A, person_id) for person_id in range(1, 4)]
    queue(persons_database, [(TEAM_A, uuid, SWEEP_1) for uuid in uuids])
    # The deadline is read once at start and checked before each page and each request. The clock
    # stands still through the first request and jumps past any finite deadline afterwards.
    clock = itertools.chain([0.0] * 3, itertools.repeat(10**9))
    monkeypatch.setattr(drain, "_now_monotonic", lambda: next(clock))

    result = run_job(cluster, page_size=1, **overrides)

    totals = totals_of(result)
    assert (totals.stopped_reason, totals.persons_deleted) == (stopped_reason, expected_deleted)
    assert len(queued(persons_database)) == 3 - expected_deleted


@pytest.mark.django_db
@pytest.mark.parametrize("failing", ["rpc", "pg"])
def test_max_runtime_ends_a_retry_loop_cleanly(cluster: ClickhouseCluster, persons_database, monkeypatch, failing):
    # A request or statement that keeps failing must not retry past the deadline: the run stops
    # with max_runtime instead of failing, the row stays queued and nothing is stamped.
    fake = get_active_fake()
    gone = seed_tombstoned(fake, TEAM_A, 1)
    queue(persons_database, [(TEAM_A, gone, SWEEP_1)])
    if failing == "rpc":
        fail_with(monkeypatch, fake, [grpc.StatusCode.UNAVAILABLE] * 50)
    else:
        monkeypatch.setattr(
            drain, "_delete_queue_rows", lambda *args: (_ for _ in ()).throw(psycopg2.OperationalError("lost"))
        )
    record_pauses(monkeypatch)
    # Read at start, before the page and before the request; the check inside the retry loop is
    # past the deadline.
    clock = itertools.chain([0.0] * 3, itertools.repeat(10**9))
    monkeypatch.setattr(drain, "_now_monotonic", lambda: next(clock))

    result = run_job(cluster)

    assert result.success
    totals = totals_of(result)
    assert totals.stopped_reason == "max_runtime"
    assert (totals.rpc_errors, totals.rpc_calls) == ((1, 0) if failing == "rpc" else (0, 1))
    assert queued(persons_database) == [(TEAM_A, gone, SWEEP_1, None)]
    assert totals.rows_stamped_blocked == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "errors,window,expect_success,expected_connects,message",
    [
        ([psycopg2.OperationalError("server closed the connection unexpectedly")], 600.0, True, 2, ""),
        ([psycopg2.InterfaceError("connection already closed")] * 50, 0.0, False, 1, "kept failing"),
        ([_pg_error("23505")], 600.0, False, 1, "statement failed"),
    ],
)
def test_queue_statement_failures_reconnect_and_retry_inside_the_window(
    cluster: ClickhouseCluster,
    persons_database,
    monkeypatch,
    errors,
    window,
    expect_success,
    expected_connects,
    message,
):
    # A lost connection is reopened and the idempotent statement run again after a backoff; a
    # connection lost past the window, or an error no retry can clear, fails the run.
    fake = get_active_fake()
    gone = seed_tombstoned(fake, TEAM_A, 1)
    queue(persons_database, [(TEAM_A, gone, SWEEP_1)])
    pending = list(errors)
    original_delete = drain._delete_queue_rows

    def flaky_delete(cursor, chunk, person_uuids):
        if pending:
            raise pending.pop(0)
        return original_delete(cursor, chunk, person_uuids)

    connects: list[str] = []
    original_connect = drain._connect

    def counting_connect(url: str):
        connects.append(url)
        return original_connect(url)

    monkeypatch.setattr(drain, "_delete_queue_rows", flaky_delete)
    monkeypatch.setattr(drain, "_connect", counting_connect)
    pauses = record_pauses(monkeypatch)

    result = run_job(cluster, pg_retry_window_seconds=window, raise_on_error=False)

    assert result.success is expect_success
    assert len(connects) == expected_connects
    if expect_success:
        assert queued(persons_database) == []
        assert totals_of(result).pg_reconnects == 1
        assert drain.PG_RETRY_BACKOFF_SECONDS in pauses
        return
    description, metadata = failure_of(result)
    assert message in description
    assert metadata["pg_reconnects"].value == 0
    # personhog had already answered, so the person is gone; the row stays and resolves as not
    # found on the next run.
    assert queued(persons_database) == [(TEAM_A, gone, SWEEP_1, None)]


@pytest.mark.parametrize(
    "rows,rpc_batch_size,expected",
    [
        ([], 3, []),
        (
            [
                QueueRow(team_id=1, person_uuid="a", deleted_at=SWEEP_1),
                QueueRow(team_id=1, person_uuid="b", deleted_at=SWEEP_1),
            ],
            3,
            [Chunk(team_id=1, deleted_at=SWEEP_1, person_uuids=("a", "b"))],
        ),
        (
            [
                QueueRow(team_id=1, person_uuid="a", deleted_at=SWEEP_1),
                QueueRow(team_id=1, person_uuid="b", deleted_at=SWEEP_2),
                QueueRow(team_id=2, person_uuid="c", deleted_at=SWEEP_1),
            ],
            3,
            [
                Chunk(team_id=1, deleted_at=SWEEP_1, person_uuids=("a",)),
                Chunk(team_id=1, deleted_at=SWEEP_2, person_uuids=("b",)),
                Chunk(team_id=2, deleted_at=SWEEP_1, person_uuids=("c",)),
            ],
        ),
        (
            [QueueRow(team_id=1, person_uuid=uuid, deleted_at=SWEEP_1) for uuid in "abcde"],
            2,
            [
                Chunk(team_id=1, deleted_at=SWEEP_1, person_uuids=("a", "b")),
                Chunk(team_id=1, deleted_at=SWEEP_1, person_uuids=("c", "d")),
                Chunk(team_id=1, deleted_at=SWEEP_1, person_uuids=("e",)),
            ],
        ),
    ],
)
def test_chunks_for_page_groups_by_team_and_sweep_then_splits(rows, rpc_batch_size, expected):
    assert chunks_for_page(rows, rpc_batch_size) == expected


@pytest.mark.parametrize(
    "exc,expected,is_conflict",
    [
        (_pg_error("40001"), "retry", True),
        (_pg_error("40P01"), "retry", True),
        (_pg_error("55P03"), "retry", True),
        # Retries like a conflict, but it is slowness, so it stays out of the conflict counter.
        (_pg_error("57014"), "retry", False),
        # lock_timeout arrives as an OperationalError subclass: the same connection retries it.
        (type("_LockNotAvailable", (psycopg2.OperationalError,), {"pgcode": "55P03"})(), "retry", True),
        (psycopg2.OperationalError("server closed the connection unexpectedly"), "reconnect", False),
        (psycopg2.InterfaceError("connection already closed"), "reconnect", False),
        (_pg_error("23505"), None, False),
        (_pg_error(None), None, False),
        (RuntimeError("not postgres"), None, False),
    ],
)
def test_pg_recovery(exc, expected, is_conflict):
    assert pg_recovery(exc) == expected
    assert drain.pg_is_queue_conflict(exc) is is_conflict


@pytest.mark.parametrize(
    "base,failures,expected",
    [(2.0, 1, 2.0), (2.0, 4, 16.0), (2.0, 6, 60.0), (0.0, 3, 0.0)],
)
def test_backoff_doubles_per_failure_up_to_the_cap(base, failures, expected):
    assert backoff_seconds(base, failures) == expected


@pytest.mark.django_db
def test_pauses_after_every_request_by_pause_ms_plus_latency(cluster: ClickhouseCluster, persons_database, monkeypatch):
    # The pause is the drain's only throttle on the persons writer. Removing it, or applying it
    # per page instead of per request, would turn a bounded background job into a burst.
    fake = get_active_fake()
    uuids = [seed_tombstoned(fake, TEAM_A, person_id) for person_id in range(1, 4)]
    queue(persons_database, [(TEAM_A, uuid, SWEEP_1) for uuid in uuids])
    pauses = record_pauses(monkeypatch)

    result = run_job(cluster, rpc_batch_size=1, pause_ms=250, latency_multiplier=2.0)

    totals = totals_of(result)
    assert len(pauses) == totals.rpc_calls == 3
    assert all(pause >= 0.25 for pause in pauses), pauses
    assert round(sum(pause - 0.25 for pause in pauses), 6) == round(2.0 * totals.rpc_seconds_total, 6)
    assert 0 < totals.rpc_seconds_last <= totals.rpc_seconds_max <= totals.rpc_seconds_total


@contextmanager
def _capturing_push(registry: CollectorRegistry) -> Iterator[CollectorRegistry]:
    yield registry


def publish(totals: DrainTotals) -> tuple[CollectorRegistry, list[str]]:
    registry = CollectorRegistry()
    pushed_jobs: list[str] = []

    def fake_push(job: str) -> AbstractContextManager[CollectorRegistry]:
        pushed_jobs.append(job)
        return _capturing_push(registry)

    with patch.object(drain, "pushed_metrics_registry", fake_push):
        drain.publish_drain_metrics(dagster.build_op_context(), totals)
    return registry, pushed_jobs


def test_a_dry_run_publishes_no_metrics():
    registry, pushed_jobs = publish(DrainTotals(dry_run=True, rows_read=5))

    # The helper pushes with PUT, which replaces the whole job. Entering it with an empty
    # registry would delete the last-success gauge, so not entering it at all is the assertion.
    assert pushed_jobs == []
    assert list(registry.collect()) == []


def test_publishes_every_measurement_the_run_took():
    totals = DrainTotals(
        rows_read=5,
        persons_deleted=3,
        persons_skipped_live=2,
        persons_not_found=7,
        persons_blocked=1,
        rows_deleted=40,
        rows_stamped_blocked=1,
        requests_pending_resent=4,
        queue_rows_estimate_at_start=1000,
        step_rows_min=250,
        rpc_errors=2,
        pg_reconnects=1,
        rpc_seconds_max=1.5,
    )

    registry, pushed_jobs = publish(totals)

    assert pushed_jobs == [drain.DRAIN_METRICS_JOB]
    prefix = "posthog_person_pg_cleanup_drain_"
    assert {
        name: registry.get_sample_value(f"{prefix}{name}")
        for name in (
            "queue_rows_estimate_at_start",
            "rows_read",
            "persons_deleted",
            "persons_skipped_live",
            "persons_not_found",
            "persons_blocked",
            "rows_deleted",
            "rows_stamped_blocked",
            "requests_pending_resent",
            "step_rows_min",
            "rpc_errors",
            "pg_reconnects",
            "rpc_seconds_max",
        )
    } == {
        "queue_rows_estimate_at_start": 1000,
        "rows_read": 5,
        "persons_deleted": 3,
        "persons_skipped_live": 2,
        "persons_not_found": 7,
        "persons_blocked": 1,
        "rows_deleted": 40,
        "rows_stamped_blocked": 1,
        "requests_pending_resent": 4,
        "step_rows_min": 250,
        "rpc_errors": 2,
        "pg_reconnects": 1,
        "rpc_seconds_max": 1.5,
    }
    last_success = registry.get_sample_value(f"{prefix}last_success_timestamp_seconds")
    # Wall clock, not the monotonic clock used elsewhere here: the alert subtracts it from time().
    assert last_success is not None
    assert abs(last_success - time.time()) < 60


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"rpc_timeout_seconds": 0}, "must be positive"),
        ({"max_runtime_seconds": -1}, "must not be negative"),
        ({"blocked_retry_hours": -1}, "must not be negative"),
        ({"rpc_batch_size": drain.RPC_MAX_UUIDS + 1}, "rpc_batch_size must be between"),
        ({"page_size": 0}, "page_size must be between"),
        ({"max_rows_per_request": drain.STEP_FLOOR_ROWS - 1}, "max_rows_per_request must be between"),
        ({"max_rows_per_request": drain.REPLICA_MAX_ROWS + 1}, "max_rows_per_request must be between"),
        ({"pause_ms": -1}, "must not be negative"),
        ({"max_blocked": -1}, "must not be negative"),
        ({"rpc_retry_window_seconds": -1}, "must not be negative"),
        ({"pg_retry_window_seconds": -1}, "must not be negative"),
    ],
)
def test_config_rejects_out_of_range_values(overrides, message):
    with pytest.raises(ValueError, match=message):
        drain.DrainConfig(**overrides)


def test_the_scheduled_config_pins_every_setting_the_drain_reads():
    config = drain.SCHEDULED_RUN_CONFIG["ops"]["drain_person_pg_cleanup_queue"]["config"]
    assert set(drain.DrainConfig.model_fields) == set(config)
    assert drain.DrainConfig.model_validate(config).dry_run is False


def test_the_job_carries_the_tags_that_bound_a_run():
    tags = drain.person_pg_cleanup_drain_job.tags
    assert tags["person_pg_cleanup_drain_concurrency"] == "v1"
    assert int(tags["dagster/max_runtime"]) > drain.DrainConfig().max_runtime_seconds
