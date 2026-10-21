import os
import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person.divergence import team_scan
from posthog.models.person.divergence.inspection import hash_distinct_id
from posthog.models.person.test.divergence_fixtures import DivergenceFixturesMixin
from posthog.models.person.util import tombstone_persons_in_postgres
from posthog.personhog_client.fake_client import get_active_fake


def _report(scan_dir: Path) -> dict[str, tuple[Any, ...]]:
    rows = [json.loads(line) for line in (scan_dir / team_scan.REPORT_FILE).read_text().splitlines()]
    report = {r["key"]: (r["flavor"], r["sub_flavor"], r["verb"], r["group"], tuple(r["also"])) for r in rows}
    assert len(report) == len(rows), "a key was reported twice"
    return report


class _Stop(Exception):
    pass


class TestTeamScan(DivergenceFixturesMixin, ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scan_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.scan_root)

    def _build_team(self) -> dict[str, str]:
        """One key per flavor the scan must find, from each of its three phases."""
        fine = self._pg_person(version=1, distinct_ids=["fine-1"])
        self._ch_person(str(fine.uuid), 1, {"email": "pg@example.com"})
        self._ch_mapping("fine-1", str(fine.uuid), 0)
        # Stale, and with no mapping, so the Postgres phase adds no_live_mappings to its row.
        stale = self._pg_person(version=1)
        self._ch_person(str(stale.uuid), 40, {"email": "old@example.com"})
        deleted = self._pg_person(version=2)
        tombstone_persons_in_postgres(self.team.pk, [deleted.uuid])
        self._ch_person(str(deleted.uuid), 7, {"email": "old@example.com"})
        # Ghost A's only ids moved to B in Postgres: fold A into B.
        new_owner = self._pg_person(version=1, distinct_ids=["moved"])
        self._ch_person(str(new_owner.uuid), 1, {"email": "pg@example.com"})
        ghost = str(uuid4())
        self._ch_person(ghost, 3, {"email": "ghost@example.com"})
        self._ch_mapping("moved", ghost, 5)
        self._ch_mapping("lost", ghost, 5)
        # C holds ids of two different old persons: no single repair is safe.
        holder = self._pg_person(version=1, distinct_ids=["x1", "x2"])
        self._ch_person(str(holder.uuid), 1, {"email": "pg@example.com"})
        self._ch_mapping("x1", str(uuid4()), 5)
        self._ch_mapping("x2", str(uuid4()), 5)
        # Only the Postgres phase can see these: ClickHouse has no row for them.
        unseen = self._pg_person(version=1, distinct_ids=["unseen-1"])
        lonely = self._pg_person(version=1)
        self._ch_person(str(lonely.uuid), 1, {"email": "pg@example.com"})
        fake = get_active_fake()
        assert fake is not None
        fake.add_person(
            team_id=self.team.pk,
            person_id=990_001,
            uuid=str(uuid4()),
            version=3,
            is_deleted=True,
            distinct_ids=["stray-1"],
        )
        return {
            "stale": str(stale.uuid),
            "deleted": str(deleted.uuid),
            "ghost": ghost,
            "new_owner": str(new_owner.uuid),
            "holder": str(holder.uuid),
            "unseen": str(unseen.uuid),
            "lonely": str(lonely.uuid),
        }

    def test_scan_reports_every_flavor_with_its_verb_and_group(self):
        keys = self._build_team()
        scan_dir = self.scan_root / "scan"
        out = StringIO()

        call_command("person_consistency", "scan", "--team-id", str(self.team.pk), "--dir", str(scan_dir), stdout=out)

        fold = f"fold:{keys['ghost']}>{keys['new_owner']}"
        assert _report(scan_dir) == {
            keys["stale"]: ("stale", None, "merge_stale", None, ("no_live_mappings",)),
            keys["deleted"]: ("deleted_visible", None, "bury", None, ()),
            keys["ghost"]: ("ghost", "historical", "fold", fold, ()),
            "moved": ("diverged", "a_absent", "fold", fold, ()),
            "lost": ("ghost", "owner_ghost", "fold", fold, ()),
            "x1": ("diverged", "ambiguous", None, f"ambiguous:{keys['holder']}", ()),
            "x2": ("diverged", "ambiguous", None, f"ambiguous:{keys['holder']}", ()),
            keys["unseen"]: ("missing_in_ch", None, "republish", None, ()),
            "unseen-1": ("missing_in_ch", None, "republish", None, ()),
            "stray-1": ("stray", None, None, None, ()),
            keys["lonely"]: ("no_live_mappings", None, None, None, ()),
        }
        summary = json.loads((scan_dir / team_scan.SUMMARY_FILE).read_text())
        assert summary["complete"] is True
        assert [g["group"] for g in summary["groups"]["largest"] if g["verb"] == "fold"] == [
            f"fold:{hash_distinct_id(self.team.pk, fold)}"
        ]
        assert keys["ghost"] not in json.dumps(summary)
        assert summary["verbs"]["fold"] == {"person_rows": 1, "mapping_rows": 2, "groups": 1}
        assert summary["groups"]["fold_modes"] == {"full": 1}
        assert summary["classified"]["person/ok/-"] == 4
        # Distinct ids stay in the report file; the command output names no key.
        for distinct_id in ("moved", "lost", "x1", "unseen-1", "stray-1"):
            assert distinct_id not in out.getvalue()

        with pytest.raises(CommandError, match="pass resume"):
            call_command("person_consistency", "scan", "--dir", str(scan_dir), stdout=StringIO())

    def test_a_deleted_team_reports_its_clickhouse_leftovers_without_repairs(self):
        keys = self._build_team()
        scan_dir = self.scan_root / "scan"
        with patch.object(team_scan.Team.objects, "filter") as team_filter:
            team_filter.return_value.exists.return_value = False
            team_scan.create_plan(scan_dir, self.team.pk)

        call_command("person_consistency", "scan", "--dir", str(scan_dir), stdout=StringIO())

        report = _report(scan_dir)
        assert {keys["stale"], keys["deleted"], keys["ghost"], "moved", "lost"} <= report.keys()
        assert set(report.values()) == {("ghost", "team_gone", None, None, ())}
        summary = json.loads((scan_dir / team_scan.SUMMARY_FILE).read_text())
        assert set(summary["verbs"]) == {"none"}
        assert {key for key in summary["classified"] if key.startswith("mapping/ghost/")} == {"mapping/ghost/team_gone"}

    def test_a_second_run_of_a_running_chunk_is_refused(self):
        self._build_team()
        scan_dir = self.scan_root / "scan"
        team_scan.create_plan(scan_dir, self.team.pk, ch_page_rows=2)
        refusals: list[str] = []

        def start_a_second_run(message: str) -> None:
            if "page" in message and not refusals:
                with pytest.raises(team_scan.ScanError, match="in use by another run") as refused:
                    team_scan.run_chunk(scan_dir, 0, resume=True)
                refusals.append(str(refused.value))

        cursor = team_scan.run_chunk(scan_dir, 0, resume=False, log=start_a_second_run)

        assert len(refusals) == 1 and cursor.phase == team_scan.DONE
        assert team_scan.run_chunk(scan_dir, 0, resume=True).phase == team_scan.DONE

    def test_chunked_paged_and_interrupted_scan_gives_the_same_report_as_one_run(self):
        self._build_team()
        whole = self.scan_root / "whole"
        team_scan.create_plan(whole, self.team.pk)
        team_scan.run_chunk(whole, 0, resume=False)
        team_scan.run_postgres(whole, resume=False)
        team_scan.finalize(whole)

        split = self.scan_root / "split"
        plan = team_scan.create_plan(split, self.team.pk, chunks=3, ch_page_rows=2, pg_page_size=2)
        assert len(plan.chunks) == 3

        def stop_after_first_page(message: str) -> None:
            if "page" in message:
                raise _Stop

        with pytest.raises(_Stop):
            team_scan.run_chunk(split, 0, resume=False, log=stop_after_first_page)
        # Bytes written after the last recorded page, as by a run that stopped mid-write.
        files = team_scan.chunk_files(split, 0)
        for path in (files.rows, files.person_keys, files.mapping_keys):
            assert path is not None
            with path.open("ab") as handle:
                handle.write(b'{"kind": "person", "key": "partial"')
        # A partial report reads each run only up to its cursor, so the half-written line is left out.
        assert team_scan.finalize(split, partial=True)["complete"] is False
        assert "partial" not in _report(split)
        for chunk in range(3):
            team_scan.run_chunk(split, chunk, resume=True)
        team_scan.run_postgres(split, resume=False)
        summary = team_scan.finalize(split)

        assert _report(split) == _report(whole)
        # The chunk bounds are sampled keys, which the summary must not carry.
        assert summary["plan"]["chunks"] == 3
        bounds = [b for c in plan.chunks for b in (c.person_from, c.person_to, c.mapping_from, c.mapping_to) if b]
        assert bounds and not any(b in json.dumps(summary) for b in bounds)
        assert len(_report(whole)) == 11

    def test_the_scan_directory_is_private_to_its_owner(self):
        scan_dir = self.scan_root / "private"
        team_scan.create_plan(scan_dir, self.team.pk)
        assert scan_dir.stat().st_mode & 0o077 == 0

        shared = self.scan_root / "shared"
        shared.mkdir(mode=0o755)
        shared.chmod(0o755)
        with pytest.raises(team_scan.ScanError, match="readable by other users"):
            team_scan.create_plan(shared, self.team.pk)

        target = self.scan_root / "target"
        target.mkdir(mode=0o700)
        linked = self.scan_root / "linked"
        linked.symlink_to(target)
        with pytest.raises(team_scan.ScanError, match="not a directory"):
            team_scan.create_plan(linked, self.team.pk)

        with patch("posthog.models.person.divergence.team_scan.os.geteuid", return_value=os.geteuid() + 1):
            with pytest.raises(team_scan.ScanError, match="owned by another user"):
                team_scan.run_chunk(scan_dir, 0, resume=False)

        # A directory opened up after its plan was written is refused when the scan resumes.
        scan_dir.chmod(0o755)
        with pytest.raises(team_scan.ScanError, match="readable by other users"):
            team_scan.run_chunk(scan_dir, 0, resume=False)
        scan_dir.chmod(0o700)


def _mapping(old: str, new: str, sub: str = "a_absent", key: str | None = None) -> dict[str, Any]:
    verb = "fold" if sub == "a_absent" else "merge"
    return {
        "kind": "mapping",
        "key": key or f"{old}-{new}",
        "flavor": "diverged",
        "sub_flavor": sub,
        "verb": verb,
        "group": None,
        "also": [],
        "evidence": {"pg": {"person_uuid": new}, "ch": {"winner_person_uuid": old}},
    }


def _ghost_mapping(owner: str) -> dict[str, Any]:
    return {
        "kind": "mapping",
        "key": f"ghost-{owner}",
        "flavor": "ghost",
        "sub_flavor": "owner_ghost",
        "verb": "restore",
        "group": None,
        "also": [],
        "evidence": {"pg": None, "ch": {"winner_person_uuid": owner}},
    }


def _ghost_person(key: str, verb: str | None) -> dict[str, Any]:
    return {
        "kind": "person",
        "key": key,
        "flavor": "ghost",
        "sub_flavor": "after_purge",
        "verb": verb,
        "group": None,
        "also": [],
    }


class TestRegroup(SimpleTestCase):
    @parameterized.expand(
        [
            # A's ids went to two persons: folding A would copy it into both.
            (
                "old_owner_split",
                [_mapping("a", "b1"), _mapping("a", "b2")],
                {"a-b1": (None, "ambiguous:a", None), "a-b2": (None, "ambiguous:a", None)},
            ),
            ("live_pair_merges", [_mapping("a", "b", sub="a_live")], {"a-b": ("merge", "merge:a>b", None)}),
            # Every id of A moved to B, so no ghost id is left to merge from.
            ("absent_pair_without_ghost_ids_folds_light", [_mapping("a", "b")], {"a-b": ("fold", "fold:a>b", "light")}),
            (
                "absent_pair_with_a_ghost_id_folds_full",
                [_mapping("a", "b"), _ghost_mapping("a")],
                {"a-b": ("fold", "fold:a>b", "full"), "ghost-a": ("fold", "fold:a>b", "full")},
            ),
            (
                "ghost_mapping_restores_with_its_owner",
                [_ghost_person("a", "restore"), _ghost_mapping("a")],
                {"a": ("restore", "restore:a", None), "ghost-a": ("restore", "restore:a", None)},
            ),
            (
                "ghost_mapping_stays_with_an_unrepaired_owner",
                [_ghost_person("a", None), _ghost_mapping("a")],
                {"a": (None, None, None), "ghost-a": (None, None, None)},
            ),
            # ClickHouse holds the owner's tombstone, so no person row asks to restore it.
            ("ghost_mapping_without_an_owner_row_stays", [_ghost_mapping("a")], {"ghost-a": (None, None, None)}),
        ]
    )
    def test_cross_key_groups(self, _name: str, rows: list[dict[str, Any]], expected: dict[str, tuple[Any, Any, Any]]):
        groups = team_scan._Groups()
        for row in rows:
            groups.observe(row)

        final = [team_scan._regroup(dict(row), groups) for row in rows]

        assert {r["key"]: (r["verb"], r["group"], r.get("fold_mode")) for r in final if r is not None} == expected
