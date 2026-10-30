import os
import json
import shutil
import signal
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from confluent_kafka import KafkaError
from parameterized import parameterized

from posthog.kafka_client.client import ClickhouseProducer, ProduceResult
from posthog.kafka_client.topics import KAFKA_PERSON
from posthog.models.person.divergence import repairs, team_scan, verbs
from posthog.models.person.divergence.cleanup_queue import PG_CLEANUP_QUEUE_TABLE
from posthog.models.person.test.divergence_fixtures import DivergenceFixturesMixin
from posthog.models.person.util import tombstone_persons_in_postgres
from posthog.personhog_client.fake_client import get_active_fake
from posthog.persons_db import persons_db_connection


class _Stop(Exception):
    pass


class TestRepairVerbs(DivergenceFixturesMixin, ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.scans = 0

    def _scan(self) -> tuple[Path, dict[str, tuple[str, str | None]]]:
        self.scans += 1
        scan_dir = self.root / f"scan-{self.scans}"
        team_scan.create_plan(scan_dir, self.team.pk)
        team_scan.run_chunk(scan_dir, 0, resume=False)
        team_scan.run_postgres(scan_dir, resume=False)
        team_scan.finalize(scan_dir)
        rows = [json.loads(line) for line in (scan_dir / team_scan.REPORT_FILE).read_text().splitlines()]
        return scan_dir, {r["key"]: (r["flavor"], r["verb"]) for r in rows}

    def _run(self, scan_dir: Path, verb: str, *, apply: bool, name: str = "actions", **kwargs: Any) -> list[dict]:
        actions_path = scan_dir / f"{name}-{verb}.jsonl"
        verbs.run_verb(scan_dir, verb, apply=apply, actions_path=actions_path, **kwargs)
        return [json.loads(line) for line in actions_path.read_text().splitlines()]

    def _mapped_person(self, version: int):
        distinct_id = f"did-{uuid4()}"
        person = self._pg_person(version=version, distinct_ids=[distinct_id])
        self._ch_mapping(distinct_id, str(person.uuid), 0)
        return person

    def _person_with_ch(self, version: int, distinct_ids: list[str] | None = None):
        person = self._pg_person(version=version, distinct_ids=distinct_ids)
        self._ch_person(str(person.uuid), version, {"email": "pg@example.com"})
        for distinct_id in distinct_ids or []:
            self._ch_mapping(distinct_id, str(person.uuid), 0)
        return person

    def test_republish_reports_in_a_dry_run_and_clears_every_row_when_applied(self):
        hidden = self._mapped_person(1)
        self._ch_person(str(hidden.uuid), 1, {"email": "pg@example.com"})
        self._ch_person(str(hidden.uuid), 100, {}, deleted=True)
        blanked = self._mapped_person(105)
        self._ch_person(str(blanked.uuid), 1, {"email": "kept@example.com"})
        self._ch_person(str(blanked.uuid), 105, {})
        tied = self._mapped_person(2)
        self._ch_person(str(tied.uuid), 2, {"email": "one@example.com"})
        self._ch_person(str(tied.uuid), 2, {"email": "two@example.com"})
        owner = self._person_with_ch(1, ["m-stale"])
        self._ch_mapping("m-stale", str(owner.uuid), 5)
        scan_dir, before = self._scan()
        expected = {
            str(hidden.uuid): ("hidden", "republish"),
            str(blanked.uuid): ("blanked", "republish"),
            str(tied.uuid): ("tie", "republish"),
            "m-stale": ("stale", "republish"),
        }
        assert before == expected

        dry = self._run(scan_dir, "republish", apply=False, name="dry")

        assert {a["key"]: a["outcome"] for a in dry if a["outcome"] != "skipped_not_divergent"} == dict.fromkeys(
            expected, "would_repair"
        )
        assert self._scan()[1] == expected

        applied = self._run(scan_dir, "republish", apply=True)

        assert {a["key"]: a["outcome"] for a in applied if a["outcome"] != "skipped_not_divergent"} == dict.fromkeys(
            expected, "repaired"
        )
        assert self._scan()[1] == {}

    def test_resume_skips_keys_an_earlier_run_finished(self):
        first, second = self._mapped_person(1), self._mapped_person(1)
        for person in (first, second):
            self._ch_person(str(person.uuid), 1, {"email": "pg@example.com"})
            self._ch_person(str(person.uuid), 100, {}, deleted=True)
        scan_dir, _ = self._scan()

        canary = self._run(scan_dir, "republish", apply=True, limit=1)
        rest = self._run(scan_dir, "republish", apply=True, resume=True)

        canary_persons = [(a["key"], a["outcome"]) for a in canary if a["kind"] == "person"]
        assert len(canary_persons) == 1 and canary_persons[0][1] == "repaired"
        resumed = [a["key"] for a in rest[len(canary) :] if a["kind"] == "person"]
        assert resumed == [k for k in (str(first.uuid), str(second.uuid)) if k != canary_persons[0][0]]
        assert self._scan()[1] == {}

    def test_bury_and_detach_tombstone_what_postgres_deleted(self):
        deleted = self._pg_person(version=2)
        tombstone_persons_in_postgres(self.team.pk, [deleted.uuid])
        self._ch_person(str(deleted.uuid), 7, {"email": "old@example.com"})
        fake = get_active_fake()
        assert fake is not None
        holder = fake.add_person(
            team_id=self.team.pk,
            person_id=990_001,
            uuid=str(uuid4()),
            version=0,
            distinct_ids=["gone", "unpublished", "holder-1"],
            distinct_id_versions={"gone": 3, "unpublished": 3},
            tombstoned_distinct_ids=["gone", "unpublished"],
        )
        self._ch_person(holder.uuid, 0, {})
        self._ch_mapping("gone", holder.uuid, 5)
        self._ch_mapping("unpublished", holder.uuid, 1)
        self._ch_mapping("holder-1", holder.uuid, 0)

        def stray_owner(person_id: int, *distinct_ids: str) -> str:
            return fake.add_person(
                team_id=self.team.pk,
                person_id=person_id,
                uuid=str(uuid4()),
                version=3,
                is_deleted=True,
                distinct_ids=list(distinct_ids),
            ).uuid

        # No ClickHouse rows for the strays.
        nothing_in_ch = stray_owner(990_010, "s-none", "s-later-diverged")
        # ClickHouse resolves the stray to its owner, which still waits for the sweep, at a version above Postgres.
        pending = stray_owner(990_011, "s-pending")
        self._ch_person(pending, 3, {}, deleted=True)
        self._ch_mapping("s-pending", pending, 5)
        # The owner's tombstone never reached ClickHouse.
        visible = stray_owner(990_012, "s-owner-visible")
        self._ch_person(visible, 2, {"email": "v@example.com"})
        self._ch_mapping("s-owner-visible", visible, 0)
        # ClickHouse resolves the stray to another person.
        differs = stray_owner(990_013, "s-differs")
        self._ch_person(differs, 3, {}, deleted=True)
        self._ch_mapping("s-differs", holder.uuid, 4)
        # The owner is gone from ClickHouse, but the stray still has rows there.
        outlived = stray_owner(990_014, "s-outlived")
        self._ch_mapping("s-outlived", outlived, 0)
        # A sweep already queued the owner, so it is swept even though its ClickHouse rows show up again.
        requeued = stray_owner(990_015, "s-requeued")
        self._ch_person(requeued, 3, {}, deleted=True)
        self._ch_mapping("s-requeued", requeued, 0)
        # Rows at ClickHouse's top version name two owners.
        tied = stray_owner(990_016, "s-tied")
        self._ch_person(tied, 3, {}, deleted=True)
        self._ch_mapping("s-tied", tied, 2)
        self._ch_mapping("s-tied", holder.uuid, 2)
        # Its only stray has no ClickHouse rows, so detaching it leaves the owner nothing live.
        released = stray_owner(990_017, "s-released")
        # Queued by an earlier sweep, then tombstoned again above that bound: the next sweep takes it.
        retombstoned = stray_owner(990_018, "s-retombstoned")
        self._ch_person(retombstoned, 5, {}, deleted=True)
        self._ch_mapping("s-retombstoned", retombstoned, 0)
        self._queue_person(retombstoned, max_version=3)
        self._queue_person(nothing_in_ch, blocked=True)
        self._queue_person(requeued, blocked=True)
        self._queue_person(released, blocked=True)

        scan_dir, before = self._scan()
        assert before == {
            str(deleted.uuid): ("deleted_visible", "bury"),
            "gone": ("deleted_visible", "bury"),
            "unpublished": ("deleted_visible", "bury"),
            visible: ("deleted_visible", "bury"),
            "s-none": ("stray", "detach"),
            "s-later-diverged": ("stray", "detach"),
            "s-pending": ("stray", "detach"),
            "s-released": ("stray", "detach"),
            "s-retombstoned": ("stray", "detach"),
            "s-owner-visible": ("stray", None),
            "s-differs": ("stray", None),
            "s-outlived": ("stray", None),
            "s-requeued": ("stray", None),
            "s-tied": ("stray", None),
        }
        assert self._sub_flavors(scan_dir, "s-owner-visible", "s-differs", "s-outlived", "s-requeued", "s-tied") == [
            "owner_visible",
            "ch_owner_differs",
            "rows_outlive_owner",
            "rows_outlive_owner",
            "ch_tie",
        ]

        buried = self._run(scan_dir, "bury", apply=True)
        # ClickHouse changes after the scan: detach re-checks before it writes.
        self._ch_mapping("s-later-diverged", holder.uuid, 2)
        planned = self._run(scan_dir, "detach", apply=False, name="dry")
        detached = self._run(scan_dir, "detach", apply=True)

        assert {a["key"]: a["outcome"] for a in buried} == {
            str(deleted.uuid): "republished",
            "gone": "buried",
            "unpublished": "buried",
            visible: "republished",
        }
        assert {a["key"]: a["outcome"] for a in planned} == {
            "s-none": "would_detach",
            "s-later-diverged": "skipped_ch_owner_differs",
            "s-pending": "would_detach",
            "s-released": "would_detach",
            "s-retombstoned": "would_detach",
        }
        assert {a["key"]: (a["outcome"], a["detail"].get("version")) for a in detached} == {
            "s-none": ("detached", 1),
            "s-later-diverged": ("skipped_ch_owner_differs", None),
            "s-pending": ("detached", 6),
            "s-released": ("detached", 1),
            "s-retombstoned": ("detached", 1),
        }
        # Released only once the owner has no live distinct id left: s-later-diverged still holds its owner.
        assert not self._queue_blocked(released)
        assert self._queue_blocked(nothing_in_ch)
        assert self._queue_blocked(requeued)

        rescan_dir, after = self._scan()
        assert after == {
            "s-later-diverged": ("stray", None),
            "s-pending": ("awaiting_sweep", None),
            "s-retombstoned": ("awaiting_sweep", None),
            "s-owner-visible": ("stray", "detach"),
            "s-differs": ("stray", None),
            "s-outlived": ("stray", None),
            "s-requeued": ("stray", None),
            "s-tied": ("stray", None),
        }

        assert [(a["key"], a["outcome"]) for a in self._run(rescan_dir, "detach", apply=True)] == [
            ("s-owner-visible", "detached")
        ]
        assert self._scan()[1]["s-owner-visible"] == ("awaiting_sweep", None)

        # A report from before the owner was pending still names bury; bury re-checks and leaves it to the sweep.
        report = rescan_dir / team_scan.REPORT_FILE
        stale = [json.loads(line) for line in report.read_text().splitlines()]
        report.write_text(
            "".join(json.dumps({**r, "verb": "bury"} if r["key"] == "s-pending" else r) + "\n" for r in stale)
        )
        assert [(a["key"], a["outcome"]) for a in self._run(rescan_dir, "bury", apply=True)] == [
            ("s-pending", "skipped_awaiting_sweep")
        ]

    def test_bury_only_raises_postgres_for_a_mapping_the_sweep_removes_with_its_owner(self):
        fake = get_active_fake()
        assert fake is not None
        owner = fake.add_person(
            team_id=self.team.pk,
            person_id=990_020,
            uuid=str(uuid4()),
            version=3,
            is_deleted=True,
            distinct_ids=["t-below"],
            distinct_id_versions={"t-below": 2},
            tombstoned_distinct_ids=["t-below"],
        ).uuid
        self._ch_person(owner, 3, {}, deleted=True)
        self._ch_mapping("t-below", owner, 4)
        scan_dir, before = self._scan()
        assert before == {"t-below": ("deleted_visible", "bury")}

        planned = self._run(scan_dir, "bury", apply=False, name="dry")
        raised = self._run(scan_dir, "bury", apply=True)

        assert [(a["outcome"], a["detail"]["target_version"]) for a in planned] == [("would_raise_for_sweep", 5)]
        assert [(a["outcome"], a["detail"]["version"]) for a in raised] == [("raised_for_sweep", 5)]
        # Still live in ClickHouse, so no tombstone was published; Postgres is now above it.
        assert self._scan()[1] == {"t-below": ("awaiting_sweep", None)}

    def _sub_flavors(self, scan_dir: Path, *keys: str) -> list[str | None]:
        rows = {r["key"]: r for r in map(json.loads, (scan_dir / team_scan.REPORT_FILE).read_text().splitlines())}
        return [rows[key]["sub_flavor"] for key in keys]

    def _hidden_person_with_stale_mapping(self) -> str:
        person = self._pg_person(version=1, distinct_ids=["h-1"])
        self._ch_person(str(person.uuid), 1, {"email": "pg@example.com"})
        self._ch_person(str(person.uuid), 100, {}, deleted=True)
        self._ch_mapping("h-1", str(person.uuid), 5)
        return str(person.uuid)

    def _tombstoned_mapping_visible_in_ch(self) -> str:
        fake = get_active_fake()
        assert fake is not None
        holder = fake.add_person(
            team_id=self.team.pk,
            person_id=990_003,
            uuid=str(uuid4()),
            version=0,
            distinct_ids=["gone", "holder-1"],
            distinct_id_versions={"gone": 3},
            tombstoned_distinct_ids=["gone"],
        )
        self._ch_person(holder.uuid, 0, {})
        self._ch_mapping("gone", holder.uuid, 5)
        self._ch_mapping("holder-1", holder.uuid, 0)
        return "gone"

    @parameterized.expand(
        [
            ("republish_after_person_raise", "republish", "repairs.raise_person_version"),
            ("republish_after_mapping_raise", "republish", "repairs._raise_mapping_version_floors"),
            ("republish_after_person_publish", "republish", "repairs._publish_person"),
            ("republish_after_mapping_publish", "republish", "repairs.create_person_distinct_id"),
            ("bury_after_mapping_raise", "bury", "repairs._raise_mapping_version_floor"),
            ("bury_after_mapping_publish", "bury", "verbs.create_person_distinct_id"),
        ]
    )
    def test_a_run_stopped_after_any_step_converges_on_rerun(self, _name: str, verb: str, step: str):
        if verb == "republish":
            self._hidden_person_with_stale_mapping()
        else:
            self._tombstoned_mapping_visible_in_ch()
        scan_dir, before = self._scan()
        assert {v for _, v in before.values()} == {verb}
        module, name = step.split(".")
        target = f"posthog.models.person.divergence.{module}.{name}"
        original = getattr({"repairs": repairs, "verbs": verbs}[module], name)

        def step_then_stop(*args: Any, **kwargs: Any) -> Any:
            original(*args, **kwargs)
            raise _Stop

        with patch(target, side_effect=step_then_stop), pytest.raises(_Stop):
            self._run(scan_dir, verb, apply=True)
        self._run(scan_dir, verb, apply=True, resume=True)

        assert self._scan()[1] == {}

    # Republish counts a failed delivery after the run; the orphan repair behind bury raises on it.
    @parameterized.expand([("republish", False), ("bury", True)])
    def test_a_publish_that_did_not_land_is_retried_on_resume(self, verb: str, raises: bool):
        if verb == "republish":
            key = self._hidden_person_with_stale_mapping()
        else:
            deleted = self._pg_person(version=2)
            tombstone_persons_in_postgres(self.team.pk, [deleted.uuid])
            self._ch_person(str(deleted.uuid), 7, {"email": "old@example.com"})
            key = str(deleted.uuid)
        scan_dir, _ = self._scan()
        failed = ProduceResult(topic=KAFKA_PERSON)
        failed.set_result(KafkaError(-192, "Local: Message timed out"), None)
        actions_path = scan_dir / f"{verb}.jsonl"

        with patch.object(ClickhouseProducer, "produce", return_value=failed):
            if raises:
                with pytest.raises(Exception):
                    verbs.run_verb(scan_dir, verb, apply=True, actions_path=actions_path)
            else:
                counts = verbs.run_verb(scan_dir, verb, apply=True, actions_path=actions_path)
                assert counts["undelivered"] > 0
        last = {}
        for action in map(json.loads, actions_path.read_text().splitlines()):
            last[action["key"]] = action["outcome"]
        assert last[key] == "undelivered"

        verbs.run_verb(scan_dir, verb, apply=True, actions_path=actions_path, resume=True)

        assert self._scan()[1] == {}

    def _queue_person(self, person_uuid: str, *, blocked: bool = False, max_version: int = 3) -> None:
        with persons_db_connection(writer=True) as conn, conn.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {PG_CLEANUP_QUEUE_TABLE} (team_id, person_uuid, deleted_at, max_version, blocked_at) "
                f"VALUES (%s, %s, now(), %s, {'now()' if blocked else 'NULL'})",
                [self.team.pk, person_uuid, max_version],
            )

    def _queue_blocked(self, person_uuid: str) -> bool:
        with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
            cursor.execute(
                f"SELECT blocked_at IS NOT NULL FROM {PG_CLEANUP_QUEUE_TABLE} WHERE team_id = %s AND person_uuid = %s",
                [self.team.pk, person_uuid],
            )
            return cursor.fetchone()[0]

    def test_a_run_stopped_by_sigterm_records_its_undelivered_keys_for_resume(self):
        key = self._hidden_person_with_stale_mapping()
        scan_dir, _ = self._scan()
        failed = ProduceResult(topic=KAFKA_PERSON)
        failed.set_result(KafkaError(-192, "Local: Message timed out"), None)
        actions_path = scan_dir / "republish.jsonl"
        republish = verbs.VERBS["republish"]

        def republish_then_sigterm(rows: list[dict], context: verbs.VerbContext) -> None:
            republish(rows, context)
            os.kill(os.getpid(), signal.SIGTERM)

        with (
            patch.object(ClickhouseProducer, "produce", return_value=failed),
            patch.dict(verbs.VERBS, {"republish": republish_then_sigterm}),
            pytest.raises(SystemExit),
        ):
            verbs.run_verb(scan_dir, "republish", apply=True, actions_path=actions_path)

        last = {a["key"]: a["outcome"] for a in map(json.loads, actions_path.read_text().splitlines())}
        assert last[key] == "undelivered"
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL

    def test_bury_paces_each_tombstone_call(self):
        for version in (2, 3):
            deleted = self._pg_person(version=version)
            tombstone_persons_in_postgres(self.team.pk, [deleted.uuid])
            self._ch_person(str(deleted.uuid), 7, {"email": "old@example.com"})
        scan_dir, _ = self._scan()

        with (
            patch.object(repairs, "_WRITE_BATCH_SIZE", 1),
            patch.object(repairs._WritePacer, "before_write", autospec=True) as before_write,
        ):
            outcomes = self._run(scan_dir, "bury", apply=True)

        assert [a["outcome"] for a in outcomes] == ["republished", "republished"]
        assert before_write.call_count == 2

    def test_merge_stale_sends_clickhouse_only_properties_then_republishes_once_ingestion_applied_them(self):
        stale = self._pg_person(version=1, distinct_ids=["s-1"])
        self._ch_person(str(stale.uuid), 40, {"email": "pg@example.com", "plan": "pro"})
        self._ch_mapping("s-1", str(stale.uuid), 0)
        scan_dir, before = self._scan()
        assert before == {str(stale.uuid): ("stale", "merge_stale")}

        with patch("posthog.models.person.divergence.stale_merge.capture_internal") as capture:
            first = self._run(scan_dir, "merge_stale", apply=True)

        assert [(a["key"], a["outcome"]) for a in first if a["kind"] == "person"] == [(str(stale.uuid), "merge_queued")]
        assert capture.call_args.kwargs["distinct_id"] == "s-1"
        assert capture.call_args.kwargs["properties"] == {"$set_once": {"plan": "pro"}}

        fake = get_active_fake()
        assert fake is not None
        stored = fake.stored_person(self.team.pk, str(stale.uuid))
        assert stored is not None
        stored.properties = json.dumps({"email": "pg@example.com", "plan": "pro"}).encode()
        with patch("posthog.models.person.divergence.stale_merge.capture_internal") as capture:
            second = self._run(scan_dir, "merge_stale", apply=True, resume=True)

        capture.assert_not_called()
        assert [(a["key"], a["outcome"]) for a in second[len(first) :] if a["kind"] == "person"] == [
            (str(stale.uuid), "repaired")
        ]
        assert self._scan()[1] == {}
