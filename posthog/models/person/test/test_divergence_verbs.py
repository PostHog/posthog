import json
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.models.person.divergence import team_scan, verbs
from posthog.models.person.test.divergence_fixtures import DivergenceFixturesMixin
from posthog.models.person.util import tombstone_persons_in_postgres
from posthog.personhog_client.fake_client import get_active_fake


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

    def test_bury_and_detach_stray_tombstone_what_postgres_deleted(self):
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
            distinct_ids=["gone", "holder-1"],
            distinct_id_versions={"gone": 3},
            tombstoned_distinct_ids=["gone"],
        )
        self._ch_person(holder.uuid, 0, {})
        self._ch_mapping("gone", holder.uuid, 5)
        self._ch_mapping("holder-1", holder.uuid, 0)
        stray_owner = fake.add_person(
            team_id=self.team.pk,
            person_id=990_002,
            uuid=str(uuid4()),
            version=3,
            is_deleted=True,
            distinct_ids=["stray-1"],
        )
        self._ch_mapping("stray-1", stray_owner.uuid, 0)
        scan_dir, before = self._scan()
        assert before == {
            str(deleted.uuid): ("deleted_visible", "bury"),
            "gone": ("deleted_visible", "bury"),
            "stray-1": ("stray", "detach_stray"),
        }

        buried = self._run(scan_dir, "bury", apply=True)
        detached = self._run(scan_dir, "detach_stray", apply=True)

        assert {a["key"]: a["outcome"] for a in buried} == {str(deleted.uuid): "republished", "gone": "buried"}
        assert [(a["key"], a["outcome"]) for a in detached] == [("stray-1", "detached")]
        assert self._scan()[1] == {}

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
