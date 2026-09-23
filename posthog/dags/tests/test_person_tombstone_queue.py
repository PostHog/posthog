from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

import dagster

from posthog.clickhouse.client import sync_execute
from posthog.dags import clickhouse_cleanup
from posthog.dags.person_tombstone_queue import QueueResolution, resolve_person_tombstone_queue
from posthog.models.person.util import (
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

    def test_confirms_republishes_and_drops_queued_persons(self):
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

    def test_a_live_distinct_id_keeps_the_person_queued(self):
        person = create_person(team_id=self.team.pk, distinct_ids=["queue-did"])
        [tombstone] = tombstone_persons_in_postgres(self.team.pk, [person.uuid])
        create_person_in_ch(uuid=str(person.uuid), team_id=self.team.pk, version=tombstone.version, is_deleted=True)

        with patch("posthog.dags.person_tombstone_queue.publish_person_tombstone") as publish:
            result = self._resolve()

        publish.assert_called_once_with(self.team.pk, tombstone)
        assert [row.person_uuid for row in result.remaining] == [person.uuid]
        assert self._queued() == {person.uuid}

    def test_dry_run_acks_and_publishes_nothing(self):
        confirmed = self._tombstoned("queue-dry-confirmed", published=True)
        behind = self._tombstoned("queue-dry-behind", published=False)

        result = self._resolve(dry_run=True)

        assert [row.person_uuid for row in result.remaining] == [behind]
        assert self._queued() == {confirmed, behind}
        assert not self._ch_person_deleted(behind)

    def test_leaves_teams_outside_the_range_alone(self):
        behind = self._tombstoned("queue-range", published=False)

        result = self._resolve(min_team_id=self.team.pk + 1)

        assert result.listed == 0
        assert self._queued() == {behind}
        assert not self._ch_person_deleted(behind)


@pytest.mark.parametrize("failing", ["resolve_person_tombstone_queue", "publish_queue_gauges"])
def test_a_queue_failure_does_not_fail_the_sweep(failing):
    run = clickhouse_cleanup.CleanupRun.for_run("run", clickhouse_cleanup.CleanupConfig(dry_run=False))
    context = dagster.build_op_context(op_config={"visibility_timeout_seconds": 0, "poll_interval_seconds": 0})

    with (
        patch.object(clickhouse_cleanup, "resolve_person_tombstone_queue", return_value=QueueResolution()),
        patch.object(clickhouse_cleanup, "publish_queue_gauges"),
        patch.object(clickhouse_cleanup, failing, side_effect=RuntimeError("down")),
    ):
        assert clickhouse_cleanup.resolve_tombstone_queue(context, run=run) == run
