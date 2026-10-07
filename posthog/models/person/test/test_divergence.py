import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils.timezone import now

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models.person import Person
from posthog.models.person.divergence import (
    DivergentPerson,
    scan_hidden_persons,
    scan_stale_persons,
    scan_swept_persons,
)
from posthog.models.person.util import (
    create_person as create_person_in_ch,
    tombstone_persons_in_postgres,
)
from posthog.models.signals import mute_selected_signals
from posthog.test.persons import add_distinct_id, create_person

PG_PROPERTIES = {"email": "postgres@example.com"}
CH_PROPERTIES = {"email": "clickhouse@example.com"}

_PERSON_COLUMNS = (
    "id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted, version, last_seen_at"
)


def _utc_naive(hours_ago: float) -> datetime:
    return (now() - timedelta(hours=hours_ago)).astimezone(UTC).replace(tzinfo=None)


class TestPersonDivergence(ClickhouseTestMixin, BaseTest):
    def _pg_person(self, *, version: int, distinct_ids: dict[str, int] | None = None) -> Person:
        # Muted signals keep create_person out of ClickHouse, so each test writes exactly the rows it describes.
        with mute_selected_signals():
            person = create_person(team=self.team, version=version, properties=PG_PROPERTIES)
            for distinct_id, distinct_id_version in (distinct_ids or {}).items():
                add_distinct_id(person=person, distinct_id=distinct_id, version=distinct_id_version)
        return person

    def _ch_person_row(
        self,
        person_uuid: UUID | str,
        version: int,
        *,
        deleted: bool = False,
        hours_ago: float = 0,
        team_id: int | None = None,
    ) -> None:
        create_person_in_ch(
            team_id=team_id or self.team.pk,
            uuid=str(person_uuid),
            version=version,
            is_deleted=deleted,
            properties=CH_PROPERTIES,
            timestamp=now() - timedelta(hours=hours_ago),
        )

    def _stop_person_merges(self) -> None:
        # A background merge collapses the older rows that the stale and swept shapes are made of.
        sync_execute("SYSTEM STOP MERGES person")
        self.addCleanup(sync_execute, "SYSTEM START MERGES person")

    def _swept_rows(self, rows_by_person: dict[UUID, list[tuple[int, bool, float]]]) -> None:
        # Stopped merges also block lightweight deletes, which run as mutations, so the rows are deleted
        # in a one-part side table whose part is then attached to person.
        self._stop_person_merges()
        staging = f"person_divergence_swept_{self.team.pk}"
        sync_execute(f"DROP TABLE IF EXISTS {staging} SYNC")
        sync_execute(f"CREATE TABLE {staging} AS person ENGINE = ReplacingMergeTree(version) ORDER BY (team_id, id)")
        self.addCleanup(sync_execute, f"DROP TABLE IF EXISTS {staging} SYNC")
        sync_execute(
            f"INSERT INTO {staging} ({_PERSON_COLUMNS}) VALUES",
            [
                {
                    "id": person_uuid,
                    "created_at": _utc_naive(24),
                    "team_id": self.team.pk,
                    "properties": json.dumps(CH_PROPERTIES),
                    "is_identified": 0,
                    "_timestamp": _utc_naive(hours_ago),
                    "_offset": 0,
                    "is_deleted": int(deleted),
                    "version": version,
                    "last_seen_at": _utc_naive(24),
                }
                for person_uuid, rows in rows_by_person.items()
                for version, deleted, hours_ago in rows
            ],
            settings={"optimize_on_insert": 0},
            flush=False,
        )
        sync_execute(f"DELETE FROM {staging} WHERE 1", settings={"lightweight_deletes_sync": 2})
        sync_execute(f"ALTER TABLE person ATTACH PARTITION tuple() FROM {staging}")

    # ── Scans ────────────────────────────────────────────────────────

    def _team_scan_range(self) -> dict[str, int]:
        return {"min_team_id": self.team.pk, "max_team_id": self.team.pk + 1}

    def test_hidden_scan_reports_only_persons_live_in_postgres_behind_a_legacy_tombstone(self) -> None:
        hidden = self._pg_person(version=3)
        self._ch_person_row(hidden.uuid, 3)
        self._ch_person_row(hidden.uuid, 103, deleted=True)
        tombstoned = self._pg_person(version=3)
        tombstone_persons_in_postgres(self.team.pk, [tombstoned.uuid])
        self._ch_person_row(tombstoned.uuid, 103, deleted=True)
        self._ch_person_row(uuid4(), 103, deleted=True)
        current_tombstone = self._pg_person(version=3)
        self._ch_person_row(current_tombstone.uuid, 4, deleted=True)
        revived = self._pg_person(version=104)
        self._ch_person_row(revived.uuid, 103, deleted=True)
        self._ch_person_row(revived.uuid, 104)

        found: list[DivergentPerson] = []
        summary = scan_hidden_persons(**self._team_scan_range(), on_found=found.append, log=lambda _: None)

        assert found == [
            DivergentPerson(
                team_id=self.team.pk, person_uuid=str(hidden.uuid), kind="hidden", ch_max_version=103, pg_version=3
            )
        ]
        assert (summary.candidates, summary.divergent, summary.skipped_team_ids) == (3, 1, [])

    def test_swept_scan_reports_live_persons_whose_late_live_row_was_swept_with_the_tombstone(self) -> None:
        swept = self._pg_person(version=3)
        live_row_before_the_tombstone = self._pg_person(version=3)
        revived_after_the_sweep = self._pg_person(version=104)
        self._swept_rows(
            {
                swept.uuid: [(3, False, 3), (103, True, 2), (4, False, 1)],
                live_row_before_the_tombstone.uuid: [(3, False, 3), (103, True, 2)],
                revived_after_the_sweep.uuid: [(103, True, 2), (4, False, 1)],
            }
        )
        self._ch_person_row(revived_after_the_sweep.uuid, 104)

        found: list[DivergentPerson] = []
        summary = scan_swept_persons(**self._team_scan_range(), on_found=found.append, log=lambda _: None)

        assert found == [
            DivergentPerson(
                team_id=self.team.pk, person_uuid=str(swept.uuid), kind="swept", ch_max_version=103, pg_version=3
            )
        ]
        assert (summary.candidates, summary.divergent) == (1, 1)

    def test_stale_scan_reports_only_a_live_winner_above_postgres_with_a_late_lower_row(self) -> None:
        self._stop_person_merges()
        stale = self._pg_person(version=5)
        in_sync = self._pg_person(version=10)
        deleted_winner = self._pg_person(version=5)
        quick_retry = self._pg_person(version=5)
        for person in (stale, in_sync, deleted_winner):
            self._ch_person_row(person.uuid, 10, deleted=person is deleted_winner, hours_ago=3)
            self._ch_person_row(person.uuid, 5, hours_ago=1)
        self._ch_person_row(quick_retry.uuid, 10, hours_ago=1.5)
        self._ch_person_row(quick_retry.uuid, 5, hours_ago=1)

        found: list[DivergentPerson] = []
        summary = scan_stale_persons(
            window_days=60, **self._team_scan_range(), on_found=found.append, log=lambda _: None
        )

        assert found == [
            DivergentPerson(
                team_id=self.team.pk, person_uuid=str(stale.uuid), kind="stale", ch_max_version=10, pg_version=5
            )
        ]
        assert (summary.candidates, summary.divergent) == (2, 1)


class TestScanTeamRanges(SimpleTestCase):
    @parameterized.expand([("out_of_memory", ClickHouseQueryMemoryLimitExceeded), ("timeout", ClickHouseQueryTimeOut)])
    def test_a_team_that_fails_alone_is_skipped_and_every_other_team_is_scanned(
        self, _name: str, error: type[Exception]
    ) -> None:
        scanned: list[int] = []

        def query(_sql: str, args: dict[str, Any], **_kwargs: Any) -> list[Any]:
            teams = range(args["min_team_id"], args["max_team_id"])
            if 7 in teams:
                raise error()
            scanned.extend(teams)
            return []

        with patch("posthog.models.person.divergence.sync_execute", side_effect=query):
            summary = scan_stale_persons(
                window_days=60, min_team_id=0, max_team_id=16, team_step=8, on_found=lambda _: None, log=lambda _: None
            )

        assert summary.skipped_team_ids == [7]
        assert sorted(scanned) == [team for team in range(16) if team != 7]
