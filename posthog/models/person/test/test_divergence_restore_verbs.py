import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.person.divergence import observe, restore_verbs, team_scan, verbs
from posthog.models.person.test.divergence_fixtures import DivergenceFixturesMixin
from posthog.models.person.util import get_distinct_id_rows, tombstone_persons_in_postgres
from posthog.personhog_client.fake_client import get_active_fake

_CAPTURE = "posthog.models.person.divergence.restore_verbs.capture_internal"


class _Stop(Exception):
    pass


_SET_ONCE = "posthog.models.person.divergence.stale_merge.capture_internal"


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

    def _lost_person_split_to(
        self, survivor_ids: list[str], *, identified: bool, ghost_ids: list[str]
    ) -> tuple[str, Any]:
        survivor = self._pg_person(version=1, distinct_ids=survivor_ids)
        self._ch_person(str(survivor.uuid), 1, {"email": "pg@example.com"})
        lost = str(uuid4())
        self._ch_person(lost, 3, {"email": "lost@example.com", "plan": "pro"}, identified=identified)
        for distinct_id in survivor_ids:
            if distinct_id.startswith("moved"):
                self._ch_mapping(distinct_id, lost, 5)
            else:
                self._ch_mapping(distinct_id, str(survivor.uuid), 0)
        for distinct_id in ghost_ids:
            self._ch_mapping(distinct_id, lost, 5)
        return lost, survivor

    def test_full_fold_restores_the_lost_person_then_asks_ingestion_to_merge_it(self):
        lost, survivor = self._lost_person_split_to(["b-own", "moved"], identified=True, ghost_ids=["lost"])
        scan_dir, before = self._scan()
        group = f"fold:{lost}>{survivor.uuid}"
        assert before == {
            lost: ("ghost", "fold", group),
            "moved": ("diverged", "fold", group),
            "lost": ("ghost", "fold", group),
        }

        with patch(_CAPTURE) as capture:
            assert self._run(scan_dir, "fold", apply=False) == dict.fromkeys(before, "would_repair")
            capture.assert_not_called()
            outcomes = self._run(scan_dir, "fold", apply=True)

        assert outcomes == {lost: "merge_sent", "moved": "awaiting_merge", "lost": "restored"}
        assert capture.call_args.kwargs["event_name"] == "$merge_dangerously"
        assert capture.call_args.kwargs["distinct_id"] == "b-own"
        assert capture.call_args.kwargs["properties"] == {"alias": "lost"}
        fake = get_active_fake()
        assert fake is not None
        restored = fake.stored_person(self.team.pk, lost)
        assert restored is not None and not restored.is_deleted and restored.is_identified
        # Until ingestion merges A, the moved id stays diverged and the scan names the merge.
        assert self._scan()[1] == {"moved": ("diverged", "merge", f"merge:{lost}>{survivor.uuid}")}

    def test_full_fold_points_the_moved_id_at_the_survivor_once_ingestion_merged(self):
        lost, survivor = self._lost_person_split_to(["b-own", "moved"], identified=True, ghost_ids=["lost"])
        scan_dir, _ = self._scan()

        def ingestion_merges(_: float) -> None:
            tombstone_persons_in_postgres(self.team.pk, [UUID(lost)])

        with patch(_CAPTURE), patch.object(restore_verbs, "_sleep", side_effect=ingestion_merges):
            outcomes = self._run(scan_dir, "fold", apply=True)

        assert outcomes == {lost: "folded", "moved": "moved", "lost": "restored"}
        moved = observe.ch_mapping_states(self.team.pk, ["moved"])["moved"]
        assert (moved.winner_person_uuid, moved.winner_version > 5) == (str(survivor.uuid), True)

    def test_a_light_fold_stopped_after_burying_the_old_person_finishes_on_rerun(self):
        lost, survivor = self._lost_person_split_to(["b-own", "moved"], identified=False, ghost_ids=["lost"])
        fake = get_active_fake()
        assert fake is not None
        stored = fake.stored_person(self.team.pk, str(survivor.uuid))
        assert stored is not None
        stored.properties = json.dumps({"email": "pg@example.com", "plan": "pro"}).encode()
        scan_dir, _ = self._scan()
        original = restore_verbs.tombstone_orphaned_ch_persons

        def bury_then_stop(*args: Any, **kwargs: Any) -> Any:
            original(*args, **kwargs)
            raise _Stop

        with patch.object(restore_verbs, "tombstone_orphaned_ch_persons", side_effect=bury_then_stop):
            with pytest.raises(_Stop):
                self._run(scan_dir, "fold", apply=True)
        scan_dir, after_stop = self._scan()
        assert after_stop == {"moved": ("diverged", "republish", None)}

        assert self._run(scan_dir, "republish", apply=True)["moved"] == "repaired"
        assert self._scan()[1] == {}
        assert {r.distinct_id: r.person_uuid for r in get_distinct_id_rows(self.team.pk, ["lost"], strong=True)} == {
            "lost": str(survivor.uuid)
        }

    def test_fold_of_two_unidentified_persons_is_light_and_finishes_once_the_properties_landed(self):
        lost, survivor = self._lost_person_split_to(["b-own", "moved"], identified=False, ghost_ids=["lost"])
        scan_dir, before = self._scan()

        with patch(_SET_ONCE) as set_once:
            first = self._run(scan_dir, "fold", apply=True)

        assert first == dict.fromkeys(before, "properties_sent")
        assert set_once.call_args.kwargs["event_name"] == "$set"
        assert set_once.call_args.kwargs["properties"] == {"$set_once": {"plan": "pro"}}
        assert self._scan()[1] == before

        fake = get_active_fake()
        assert fake is not None
        stored = fake.stored_person(self.team.pk, str(survivor.uuid))
        assert stored is not None
        stored.properties = json.dumps({"email": "pg@example.com", "plan": "pro"}).encode()
        scan_dir, _ = self._scan()
        with patch(_SET_ONCE) as set_once:
            second = self._run(scan_dir, "fold", apply=True)

        set_once.assert_not_called()
        assert second == {lost: "folded", "moved": "moved", "lost": "moved"}
        assert not stored.is_identified
        assert self._scan()[1] == {}

    @parameterized.expand(
        [
            ("two_survivor_ids", ["b-own", "moved"], "$identify", {"$anon_distinct_id": "moved"}, False),
            # An identify needs two of B's ids, so B stays unidentified and the action says so.
            ("one_survivor_id", ["moved"], "$set", {}, True),
        ]
    )
    def test_light_fold_carries_identified_only_when_the_survivor_has_two_ids(
        self, _name: str, survivor_ids: list[str], event: str, extra: dict, not_carried: bool
    ):
        lost, _ = self._lost_person_split_to(survivor_ids, identified=True, ghost_ids=[])
        scan_dir, _ = self._scan()

        with patch(_SET_ONCE) as set_once:
            outcomes = self._run(scan_dir, "fold", apply=True)

        assert outcomes == {lost: "properties_sent", "moved": "properties_sent"}
        assert set_once.call_args.kwargs["event_name"] == event
        assert set_once.call_args.kwargs["properties"] == {**extra, "$set_once": {"plan": "pro"}}
        actions = [json.loads(line) for line in (scan_dir / "fold-apply.jsonl").read_text().splitlines()]
        person_action = next(a for a in actions if a["key"] == lost)
        assert person_action["detail"].get("identified_not_carried", False) is not_carried

    @parameterized.expand(
        [
            ("after_restore", "_restore_persons"),
            ("after_merge_sent", "_send_merge"),
        ]
    )
    def test_a_full_fold_stopped_after_any_step_sends_the_merge_on_rerun(self, _name: str, step: str):
        lost, _ = self._lost_person_split_to(["b-own", "moved"], identified=True, ghost_ids=["lost"])
        scan_dir, _ = self._scan()
        original = getattr(restore_verbs, step)

        def step_then_stop(*args: Any, **kwargs: Any) -> Any:
            original(*args, **kwargs)
            raise _Stop

        actions_path = scan_dir / "fold.jsonl"
        with patch(_CAPTURE), patch.object(restore_verbs, step, side_effect=step_then_stop), pytest.raises(_Stop):
            verbs.run_verb(scan_dir, "fold", apply=True, actions_path=actions_path)
        with patch(_CAPTURE) as capture:
            verbs.run_verb(scan_dir, "fold", apply=True, actions_path=actions_path, resume=True)

        assert capture.call_args.kwargs["properties"] == {"alias": "lost"}
        fake = get_active_fake()
        assert fake is not None
        assert fake.stored_person(self.team.pk, lost) is not None
        assert {r.distinct_id: r.person_uuid for r in get_distinct_id_rows(self.team.pk, ["lost"], strong=True)} == {
            "lost": lost
        }

    def test_pair_folds_an_old_person_whose_ids_went_to_two_survivors_into_the_chosen_one(self):
        first = self._pg_person(version=1, distinct_ids=["moved-1"])
        second = self._pg_person(version=1, distinct_ids=["moved-2"])
        for person in (first, second):
            self._ch_person(str(person.uuid), 1, {"email": "pg@example.com"})
        lost = str(uuid4())
        self._ch_person(lost, 3, {"plan": "pro"})
        self._ch_mapping("moved-1", lost, 5)
        self._ch_mapping("moved-2", lost, 5)
        scan_dir, before = self._scan()
        assert {key: verb for key, (_, verb, _) in before.items()} == dict.fromkeys(before, None)

        with patch(_SET_ONCE) as set_once:
            outcomes = verbs.run_verb(
                scan_dir,
                "fold",
                apply=True,
                actions_path=scan_dir / "pair.jsonl",
                pairs=[f"{lost}>{first.uuid}"],
            )

        assert outcomes == {"properties_sent": 2}
        assert set_once.call_args.kwargs["distinct_id"] == "moved-1"
        assert str(second.uuid) not in (scan_dir / "pair.jsonl").read_text()

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
