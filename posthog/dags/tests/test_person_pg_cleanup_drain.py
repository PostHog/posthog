import itertools
from datetime import UTC, datetime
from uuid import uuid4

import pytest

import grpc
import dagster
import psycopg2

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags import person_pg_cleanup_drain as drain
from posthog.dags.clickhouse_cleanup import PG_CLEANUP_QUEUE_TABLE
from posthog.dags.person_pg_cleanup_drain import (
    Chunk,
    DrainTotals,
    QueueRow,
    chunks_for_page,
    is_retryable_pg_error,
    person_pg_cleanup_drain_job,
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


def present(fake: FakePersonHogClient, team_id: int, uuid: str) -> bool:
    return fake.get_person_by_uuid(GetPersonByUuidRequest(team_id=team_id, uuid=uuid)).HasField("person")


def delete_requests(fake: FakePersonHogClient) -> list:
    return [call.request for call in fake.calls if call.method == "delete_tombstoned_persons"]


class _RpcError(grpc.RpcError):
    def __init__(self, code: grpc.StatusCode) -> None:
        super().__init__()
        self._code = code

    def code(self) -> grpc.StatusCode:
        return self._code


def fail_with(monkeypatch: pytest.MonkeyPatch, fake: FakePersonHogClient, codes: list[grpc.StatusCode]) -> None:
    # The first len(codes) calls raise the given status; later calls reach the fake.
    pending = list(codes)
    original = fake.delete_tombstoned_persons

    def wrapped(
        request: DeleteTombstonedPersonsRequest, timeout: float | None = None
    ) -> DeleteTombstonedPersonsResponse:
        if pending:
            raise _RpcError(pending.pop(0))
        return original(request, timeout=timeout)

    monkeypatch.setattr(fake, "delete_tombstoned_persons", wrapped)


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
    totals = totals_of(result)
    assert (totals.persons_deleted, totals.queue_rows_deleted, totals.stopped_reason) == (3, 3, "drained")


@pytest.mark.django_db
def test_removes_rows_for_live_and_unknown_persons_without_deleting_them(cluster: ClickhouseCluster, persons_database):
    # A live row means Postgres revived the person after the sweep queued it, and an unknown row
    # means another path already hard-deleted it. Both rows must go, or they are re-sent every run
    # and the queue fills with rows that can never resolve.
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
def test_blocked_rows_stay_queued_and_are_skipped_inside_the_retry_window(cluster: ClickhouseCluster, persons_database):
    # personhog reports a tombstoned person that still owns a live distinct id as blocked. The row
    # must survive with blocked_at set: deleting it would hide an ingestion invariant violation,
    # and re-sending it every run would hammer personhog for nothing.
    fake = get_active_fake()
    blocked = seed_blocked(fake, TEAM_A, 1)
    gone = seed_tombstoned(fake, TEAM_A, 2)
    queue(persons_database, [(TEAM_A, blocked, SWEEP_1), (TEAM_A, gone, SWEEP_1)])

    first = run_job(cluster)

    [(team_id, person_uuid, _, blocked_at)] = queued(persons_database)
    assert (team_id, person_uuid) == (TEAM_A, blocked)
    assert blocked_at is not None
    assert present(fake, TEAM_A, blocked)
    assert totals_of(first).persons_blocked == 1
    assert totals_of(first).blocked_sample == [blocked]

    second = run_job(cluster)
    assert totals_of(second).rows_read == 0, "a freshly blocked row is skipped inside the retry window"

    third = run_job(cluster, blocked_retry_hours=0)
    assert totals_of(third).persons_blocked == 1, "past the window the row is retried and reported again"


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
    # One team can hold rows from two sweep runs on one page. They travel in separate requests so
    # the queue delete can pin deleted_at; a row the sweep re-queues while its request is in flight
    # keeps the newer deleted_at and is drained next run instead of being deleted on stale evidence.
    fake = get_active_fake()
    old = seed_tombstoned(fake, TEAM_A, 1)
    new = seed_tombstoned(fake, TEAM_A, 2)
    requeued = seed_tombstoned(fake, TEAM_A, 3)
    queue(persons_database, [(TEAM_A, old, SWEEP_1), (TEAM_A, requeued, SWEEP_1), (TEAM_A, new, SWEEP_2)])
    original = fake.delete_tombstoned_persons

    def requeue_during_rpc(
        request: DeleteTombstonedPersonsRequest, timeout: float | None = None
    ) -> DeleteTombstonedPersonsResponse:
        if requeued in request.person_uuids:
            with persons_database.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {PG_CLEANUP_QUEUE_TABLE} SET deleted_at = %s WHERE person_uuid = %s",
                    (SWEEP_2, requeued),
                )
            persons_database.commit()
        return original(request, timeout=timeout)

    monkeypatch.setattr(fake, "delete_tombstoned_persons", requeue_during_rpc)

    result = run_job(cluster)

    sent = [sorted(request.person_uuids) for request in delete_requests(fake)]
    assert sorted(sent) == sorted([sorted([old, requeued]), [new]])
    assert queued(persons_database) == [(TEAM_A, requeued, SWEEP_2, None)]
    assert totals_of(result).queue_rows_deleted == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "codes,max_consecutive_failures,expect_success",
    [
        ([grpc.StatusCode.UNAVAILABLE], 5, True),
        ([grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.INTERNAL, grpc.StatusCode.UNAVAILABLE], 2, False),
    ],
)
def test_rpc_failures_are_retried_and_then_fail_the_run(
    cluster: ClickhouseCluster, persons_database, monkeypatch, codes, max_consecutive_failures, expect_success
):
    # A row is removed from the queue only after personhog answered for it. A run that gives up
    # must leave every row of the failed request in place, with its identity in the failure.
    fake = get_active_fake()
    gone = seed_tombstoned(fake, TEAM_A, 1)
    queue(persons_database, [(TEAM_A, gone, SWEEP_1)])
    fail_with(monkeypatch, fake, codes)

    result = run_job(cluster, max_consecutive_failures=max_consecutive_failures, raise_on_error=False)

    assert result.success is expect_success
    if expect_success:
        assert queued(persons_database) == []
        assert totals_of(result).rpc_errors == len(codes)
        return
    assert queued(persons_database) == [(TEAM_A, gone, SWEEP_1, None)]
    assert present(fake, TEAM_A, gone)
    failure = result.failure_data_for_node(OP)
    assert failure is not None and failure.user_failure_data is not None
    metadata = failure.user_failure_data.metadata
    assert metadata["team_id"].value == TEAM_A
    assert metadata["first_uuid"].value == gone
    assert metadata["attempts"].value == max_consecutive_failures


@pytest.mark.django_db
def test_an_unimplemented_rpc_fails_immediately_without_retrying_or_writing(
    cluster: ClickhouseCluster, persons_database, monkeypatch
):
    # An older personhog answers UNIMPLEMENTED. Retrying or falling back would be wrong: the legacy
    # delete RPC has no tombstone check, so the run must stop before it deletes anything.
    fake = get_active_fake()
    gone = seed_tombstoned(fake, TEAM_A, 1)
    queue(persons_database, [(TEAM_A, gone, SWEEP_1)])
    fail_with(monkeypatch, fake, [grpc.StatusCode.UNIMPLEMENTED] * 5)

    result = run_job(cluster, raise_on_error=False)

    assert not result.success
    assert len(delete_requests(fake)) == 0, "the wrapper raised before the fake recorded a call"
    assert queued(persons_database) == [(TEAM_A, gone, SWEEP_1, None)]
    assert present(fake, TEAM_A, gone)


@pytest.mark.django_db
def test_max_runtime_stops_between_pages_and_reports_it(cluster: ClickhouseCluster, persons_database, monkeypatch):
    fake = get_active_fake()
    uuids = [seed_tombstoned(fake, TEAM_A, person_id) for person_id in range(1, 4)]
    queue(persons_database, [(TEAM_A, uuid, SWEEP_1) for uuid in uuids])
    # The deadline is read once at start and then checked before each page and each chunk. The
    # clock stands still through the first page and jumps past the deadline afterwards.
    clock = itertools.chain([0.0, 0.0, 0.0], itertools.repeat(10**9))
    monkeypatch.setattr(drain, "_now_monotonic", lambda: next(clock))

    result = run_job(cluster, page_size=1)

    totals = totals_of(result)
    assert (totals.stopped_reason, totals.persons_deleted) == ("max_runtime", 1)
    assert len(queued(persons_database)) == 2


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


def _pg_error(pgcode: str | None) -> psycopg2.Error:
    # pgcode is a read-only attribute on psycopg2.Error, so a subclass attribute stands in for it.
    return type("_PgError", (psycopg2.Error,), {"pgcode": pgcode})()


@pytest.mark.parametrize(
    "exc,expected",
    [
        (_pg_error("40001"), True),
        (_pg_error("40P01"), True),
        (_pg_error("23505"), False),
        (_pg_error(None), False),
        (RuntimeError("not postgres"), False),
    ],
)
def test_is_retryable_pg_error(exc, expected):
    assert is_retryable_pg_error(exc) is expected


@pytest.mark.django_db
def test_pauses_after_every_request_by_pause_ms_plus_latency(cluster: ClickhouseCluster, persons_database, monkeypatch):
    # The pause is the drain's only throttle on the persons writer. Removing it, or applying it
    # per page instead of per request, would turn a bounded background job into a burst.
    fake = get_active_fake()
    uuids = [seed_tombstoned(fake, TEAM_A, person_id) for person_id in range(1, 4)]
    queue(persons_database, [(TEAM_A, uuid, SWEEP_1) for uuid in uuids])
    pauses: list[float] = []
    monkeypatch.setattr(drain, "_pause", pauses.append)

    result = run_job(cluster, rpc_batch_size=1, pause_ms=250, latency_multiplier=2.0)

    totals = totals_of(result)
    assert len(pauses) == totals.rpc_calls == 3
    assert all(pause >= 0.25 for pause in pauses), pauses
    assert [round(pause - 0.25, 6) for pause in pauses] == [round(2.0 * rpc, 6) for rpc in totals.rpc_seconds]
