from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

import dagster
from parameterized import parameterized
from prometheus_client import CollectorRegistry

from posthog.clickhouse.client import sync_execute
from posthog.dags import clickhouse_cleanup
from posthog.dags.person_tombstone_queue import (
    TEAM_ATTEMPTS,
    QueueResolution,
    clickhouse_confirmed,
    publish_queue_gauges,
    resolve_person_tombstone_queue,
)
from posthog.models import Team
from posthog.models.person.util import (
    PersonTombstone,
    QueuedPersonTombstone,
    create_person as create_person_in_ch,
    publish_person_tombstone,
    tombstone_persons_in_postgres,
)
from posthog.personhog_client.fake_client import get_active_fake
from posthog.test.persons import create_person


class TestResolvePersonTombstoneQueue(ClickhouseTestMixin, BaseTest):
    def _tombstoned(self, distinct_id: str, *, published: bool) -> UUID:
        person = create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
        [tombstone] = tombstone_persons_in_postgres(self.team.pk, [person.uuid])
        if published:
            publish_person_tombstone(self.team.pk, tombstone)
        return person.uuid

    def _resolve(self, *, dry_run: bool = False, min_team_id: int = 0, max_team_id: int = 0) -> QueueResolution:
        return resolve_person_tombstone_queue(
            dry_run=dry_run,
            min_team_id=min_team_id,
            max_team_id=max_team_id,
            visibility_timeout_seconds=0,
            poll_interval_seconds=0,
            log=lambda _: None,
        )

    def _queued(self) -> set[UUID]:
        return {UUID(person_uuid) for _, person_uuid in get_active_fake().tombstone_queue}

    def _ch_person_deleted(self, person_uuid: UUID) -> bool:
        [[is_deleted]] = sync_execute(
            "SELECT argMax(is_deleted, version) FROM person WHERE team_id = %(t)s AND id = %(u)s",
            {"t": self.team.pk, "u": str(person_uuid)},
        )
        return bool(is_deleted)

    def test_confirms_republishes_and_drops_queued_persons(self) -> None:
        confirmed = self._tombstoned("queue-confirmed", published=True)
        behind = self._tombstoned("queue-behind", published=False)
        live = create_person(team_id=self.team.pk, distinct_ids=["queue-live"]).uuid
        missing = uuid4()
        get_active_fake().tombstone_queue[(self.team.pk, str(live))] = 1
        get_active_fake().tombstone_queue[(self.team.pk, str(missing))] = 1

        result = self._resolve()

        assert (result.listed, result.dropped, result.confirmed, result.republished) == (4, 2, 2, 1)
        assert result.remaining == []
        assert self._queued() == set()
        assert self._ch_person_deleted(confirmed)
        assert self._ch_person_deleted(behind)
        assert not self._ch_person_deleted(live)

    def test_a_live_distinct_id_keeps_the_person_queued(self) -> None:
        person = create_person(team_id=self.team.pk, distinct_ids=["queue-did"])
        [tombstone] = tombstone_persons_in_postgres(self.team.pk, [person.uuid])
        create_person_in_ch(uuid=str(person.uuid), team_id=self.team.pk, version=tombstone.version, is_deleted=True)

        with patch("posthog.dags.person_tombstone_queue.publish_person_tombstone") as publish:
            result = self._resolve()

        publish.assert_called_once_with(self.team.pk, tombstone)
        assert [row.person_uuid for row in result.remaining] == [person.uuid]
        assert self._queued() == {person.uuid}

    def test_dry_run_acks_and_publishes_nothing(self) -> None:
        confirmed = self._tombstoned("queue-dry-confirmed", published=True)
        behind = self._tombstoned("queue-dry-behind", published=False)

        result = self._resolve(dry_run=True)

        assert [row.person_uuid for row in result.remaining] == [behind]
        assert self._queued() == {confirmed, behind}
        assert not self._ch_person_deleted(behind)

    def test_leaves_teams_outside_the_range_alone(self) -> None:
        behind = self._tombstoned("queue-range", published=False)

        result = self._resolve(min_team_id=self.team.pk + 1)

        assert result.listed == 0
        assert self._queued() == {behind}
        assert not self._ch_person_deleted(behind)

    def test_a_person_absent_from_clickhouse_is_republished_not_acked(self) -> None:
        person_uuid = uuid4()
        # Persons DB only: the ClickHouse rows for this person are still in flight.
        get_active_fake().add_person(
            team_id=self.team.pk, person_id=1_000_001, uuid=str(person_uuid), distinct_ids=["queue-absent"]
        )
        tombstone_persons_in_postgres(self.team.pk, [person_uuid])

        result = self._resolve()

        assert (result.republished, result.confirmed) == (1, 1)
        assert result.remaining == []
        assert self._queued() == set()
        assert self._ch_person_deleted(person_uuid)

    def test_polls_the_confirmation_in_chunks(self) -> None:
        for i in range(3):
            self._tombstoned(f"queue-chunk-{i}", published=False)

        with (
            patch("posthog.dags.person_tombstone_queue.CHUNK_SIZE", 2),
            patch("posthog.dags.person_tombstone_queue.clickhouse_confirmed", wraps=clickhouse_confirmed) as confirm,
        ):
            result = self._resolve()

        assert (result.republished, result.confirmed) == (3, 3)
        assert self._queued() == set()
        assert max(len(call.args[1]) for call in confirm.call_args_list) == 2

    @parameterized.expand([("transient", 1, 0), ("persistent", TEAM_ATTEMPTS, 1)])
    def test_retries_a_failing_team_and_leaves_it_queued_when_it_keeps_failing(
        self, _name: str, failures: int, failed_teams: int
    ) -> None:
        other = Team.objects.create(organization=self.organization)
        ours = self._tombstoned("queue-ours", published=True)
        theirs = create_person(team=other, distinct_ids=["queue-theirs"])
        tombstone_persons_in_postgres(other.pk, [theirs.uuid])
        raised = 0

        def flaky(team_id: int, tombstones: list) -> set[UUID]:
            nonlocal raised
            if team_id == other.pk and raised < failures:
                raised += 1
                raise RuntimeError("clickhouse down")
            return clickhouse_confirmed(team_id, tombstones)

        with (
            patch("posthog.dags.person_tombstone_queue.clickhouse_confirmed", side_effect=flaky),
            patch("posthog.dags.person_tombstone_queue.RETRY_BACKOFF_SECONDS", 0),
        ):
            result = self._resolve()

        # Our team is unaffected by the other team's failure.
        assert result.failed_teams == failed_teams
        assert ours not in self._queued()
        if failed_teams:
            assert [(row.team_id, row.person_uuid) for row in result.remaining] == [(other.pk, theirs.uuid)]
            assert self._queued() == {theirs.uuid}
        else:
            assert result.remaining == []
            assert self._queued() == set()

    def test_one_failed_publish_leaves_only_that_person_queued(self) -> None:
        failing = self._tombstoned("queue-publish-fails", published=False)
        passing = self._tombstoned("queue-publish-passes", published=False)
        logged: list[str] = []

        def publish(team_id: int, tombstone: PersonTombstone) -> list:
            if tombstone.uuid == failing:
                raise RuntimeError("kafka down")
            return publish_person_tombstone(team_id, tombstone)

        with patch("posthog.dags.person_tombstone_queue.publish_person_tombstone", side_effect=publish):
            result = resolve_person_tombstone_queue(
                dry_run=False,
                min_team_id=0,
                max_team_id=0,
                visibility_timeout_seconds=0,
                poll_interval_seconds=0,
                log=logged.append,
            )

        assert (result.republished, result.confirmed, result.failed_teams) == (1, 1, 0)
        assert [row.person_uuid for row in result.remaining] == [failing]
        assert self._queued() == {failing}
        assert self._ch_person_deleted(passing)
        assert any(str(failing) in line for line in logged)

    def test_pages_through_the_whole_queue(self) -> None:
        behind = {self._tombstoned(f"queue-page-{i}", published=False) for i in range(3)}

        with patch("posthog.dags.person_tombstone_queue.PAGE_SIZE", 2):
            result = self._resolve()

        # Two full pages, then the empty one that ends the walk.
        get_active_fake().assert_called("list_person_tombstone_queue", times=3)
        assert (result.listed, result.republished, result.confirmed) == (3, 3, 3)
        assert self._queued() == set()
        assert all(self._ch_person_deleted(uuid) for uuid in behind)

    def test_remaining_rows_keep_their_own_team(self) -> None:
        other = Team.objects.create(organization=self.organization)
        shared = uuid4()
        for team in (self.team, other):
            person = create_person(team=team, distinct_ids=[f"queue-shared-{team.pk}"], uuid=shared)
            tombstone_persons_in_postgres(team.pk, [person.uuid])

        with patch("posthog.dags.person_tombstone_queue.publish_person_tombstone"):
            result = self._resolve()

        assert sorted((row.team_id, row.person_uuid) for row in result.remaining) == sorted(
            [(self.team.pk, shared), (other.pk, shared)]
        )


def _queued_row(team_id: int, tombstoned_at_ms: int) -> QueuedPersonTombstone:
    return QueuedPersonTombstone(
        team_id=team_id, person_uuid=uuid4(), person_version=1, tombstoned_at_ms=tombstoned_at_ms
    )


@pytest.mark.parametrize(
    "remaining,failed_teams,expected_unresolved,expected_oldest_age",
    [
        ([], 0, 0, 0),
        ([_queued_row(1, 400_000), _queued_row(2, 100_000)], 1, 2, 900),
    ],
)
def test_publishes_the_gauges_the_alert_reads(
    remaining: list[QueuedPersonTombstone],
    failed_teams: int,
    expected_unresolved: int,
    expected_oldest_age: float,
) -> None:
    registry = CollectorRegistry()

    @contextmanager
    def capture(job_name: str):
        assert job_name == "person_tombstone_queue"
        yield registry

    with patch("posthog.dags.person_tombstone_queue.pushed_metrics_registry", capture):
        publish_queue_gauges(QueueResolution(remaining=remaining, failed_teams=failed_teams), completed_at=1_000.0)

    assert registry.get_sample_value("posthog_person_tombstone_queue_unresolved_rows") == expected_unresolved
    assert registry.get_sample_value("posthog_person_tombstone_queue_failed_teams") == failed_teams
    assert registry.get_sample_value("posthog_person_tombstone_queue_oldest_unresolved_seconds") == expected_oldest_age
    assert registry.get_sample_value("posthog_person_tombstone_queue_last_run_timestamp_seconds") == 1_000.0


@pytest.mark.parametrize("failing", ["resolve_person_tombstone_queue", "publish_queue_gauges"])
def test_a_queue_failure_does_not_fail_the_sweep(failing: str) -> None:
    run = clickhouse_cleanup.CleanupRun.for_run("run", clickhouse_cleanup.CleanupConfig(dry_run=False))
    context = dagster.build_op_context(op_config={"visibility_timeout_seconds": 0, "poll_interval_seconds": 0})

    with (
        patch.object(clickhouse_cleanup, "resolve_person_tombstone_queue", return_value=QueueResolution()),
        patch.object(clickhouse_cleanup, "publish_queue_gauges"),
        patch.object(clickhouse_cleanup, failing, side_effect=RuntimeError("down")),
    ):
        assert clickhouse_cleanup.resolve_tombstone_queue(context, run=run) == run
