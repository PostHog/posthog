import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.models.person.divergence import observe, restore_verbs, team_scan, verbs
from posthog.models.person.test.divergence_fixtures import DivergenceFixturesMixin
from posthog.models.person.util import tombstone_persons_in_postgres
from posthog.personhog_client.fake_client import get_active_fake

_CAPTURE = "posthog.models.person.divergence.restore_verbs.capture_internal"


class TestRestoreVerbs(DivergenceFixturesMixin, ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        for name, value in (("_sleep", lambda _: None), ("_MERGE_CONFIRM_SECONDS", 0.0)):
            patcher = patch.object(restore_verbs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.scans = 0

    def _scan(self, *, purged_at: datetime | None = None) -> tuple[Path, dict[str, tuple[Any, ...]]]:
        self.scans += 1
        scan_dir = self.root / f"scan-{self.scans}"
        team_scan.create_plan(scan_dir, self.team.pk, purged_at=purged_at)
        team_scan.run_chunk(scan_dir, 0, resume=False)
        team_scan.run_postgres(scan_dir, resume=False)
        team_scan.finalize(scan_dir)
        rows = [json.loads(line) for line in (scan_dir / team_scan.REPORT_FILE).read_text().splitlines()]
        return scan_dir, {r["key"]: (r["flavor"], r["verb"], r["group"]) for r in rows}

    def _run(self, scan_dir: Path, verb: str, *, apply: bool) -> dict[str, str]:
        actions_path = scan_dir / f"{verb}-{'apply' if apply else 'dry'}.jsonl"
        verbs.run_verb(scan_dir, verb, apply=apply, actions_path=actions_path)
        return {a["key"]: a["outcome"] for a in map(json.loads, actions_path.read_text().splitlines())}

    def _live_person(self, distinct_id: str, properties: dict | None = None):
        person = self._pg_person(version=1, distinct_ids=[distinct_id])
        self._ch_person(str(person.uuid), 1, properties or {"email": "pg@example.com"})
        self._ch_mapping(distinct_id, str(person.uuid), 0)
        return person

    def test_restore_rebuilds_a_lost_person_and_its_distinct_ids_from_clickhouse(self):
        lost = str(uuid4())
        self._ch_person(lost, 4, {"email": "lost@example.com"})
        self._ch_mapping("r-1", lost, 2)
        self._ch_mapping("r-2", lost, 0)
        purged_at = datetime.now(UTC) + timedelta(hours=1)
        scan_dir, before = self._scan(purged_at=purged_at)
        group = f"restore:{lost}"
        assert before == {
            lost: ("ghost", "restore", group),
            "r-1": ("ghost", "restore", group),
            "r-2": ("ghost", "restore", group),
        }

        assert self._run(scan_dir, "restore", apply=False) == dict.fromkeys(before, "would_repair")
        assert self._scan(purged_at=purged_at)[1] == before

        assert self._run(scan_dir, "restore", apply=True) == dict.fromkeys(before, "restored")

        fake = get_active_fake()
        assert fake is not None
        stored = fake.stored_person(self.team.pk, lost)
        assert stored is not None
        assert (stored.version, json.loads(stored.properties)) == (5, {"email": "lost@example.com"})
        assert self._scan(purged_at=purged_at)[1] == {}

    def test_merge_points_the_shared_ids_at_the_survivor_once_ingestion_merged(self):
        old = self._live_person("a-own")
        survivor = self._live_person("shared")
        self._ch_mapping("shared", str(old.uuid), 5)
        scan_dir, _ = self._scan()

        def ingestion_merges(_: float) -> None:
            tombstone_persons_in_postgres(self.team.pk, [old.uuid])

        with patch(_CAPTURE), patch.object(restore_verbs, "_sleep", side_effect=ingestion_merges):
            outcomes = self._run(scan_dir, "merge", apply=True)

        assert outcomes == {"shared": "moved", str(old.uuid): "merged"}
        shared = observe.ch_mapping_states(self.team.pk, ["shared"])["shared"]
        assert (shared.winner_person_uuid, shared.winner_version > 5) == (str(survivor.uuid), True)

    def test_merge_asks_ingestion_to_merge_and_leaves_the_shared_ids_until_it_did(self):
        old = self._live_person("a-own")
        survivor = self._live_person("shared")
        self._ch_mapping("shared", str(old.uuid), 5)
        scan_dir, before = self._scan()
        assert before == {"shared": ("diverged", "merge", f"merge:{old.uuid}>{survivor.uuid}")}

        with patch(_CAPTURE) as capture:
            outcomes = self._run(scan_dir, "merge", apply=True)

        assert outcomes == {"shared": "awaiting_merge", str(old.uuid): "merge_sent"}
        assert capture.call_args.kwargs["event_name"] == "$merge_dangerously"
        assert capture.call_args.kwargs["distinct_id"] == "shared"
        assert capture.call_args.kwargs["properties"] == {"alias": "a-own"}
        assert self._scan()[1] == before

    def test_restore_leaves_a_lost_person_out_when_its_only_id_was_claimed_after_the_scan(self):
        lost = str(uuid4())
        self._ch_person(lost, 4, {"email": "lost@example.com"})
        self._ch_mapping("claimed", lost, 2)
        purged_at = datetime.now(UTC) + timedelta(hours=1)
        scan_dir, before = self._scan(purged_at=purged_at)
        assert {key: verb for key, (_, verb, _) in before.items()} == {lost: "restore", "claimed": "restore"}
        self._pg_person(version=0, distinct_ids=["claimed"])

        outcomes = self._run(scan_dir, "restore", apply=True)

        assert outcomes == {lost: "skipped_no_distinct_id", "claimed": "skipped_changed"}
        fake = get_active_fake()
        assert fake is not None
        assert fake.stored_person(self.team.pk, lost) is None

    def test_fold_and_merge_skip_a_team_with_person_processing_off(self):
        old = self._live_person("a-own")
        self._live_person("shared")
        self._ch_mapping("shared", str(old.uuid), 5)
        self.team.person_processing_opt_out = True
        self.team.save()
        scan_dir, _ = self._scan()

        with patch(_CAPTURE) as capture:
            outcomes = self._run(scan_dir, "merge", apply=True)

        capture.assert_not_called()
        assert outcomes == {"shared": "skipped_person_processing_off"}
