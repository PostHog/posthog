import os
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.models.person.divergence import team_scan
from posthog.models.person.test.divergence_fixtures import DivergenceFixturesMixin
from posthog.models.person.util import tombstone_persons_in_postgres


def _chunk_rows(scan_dir: Path, chunks: int) -> dict[str, tuple[Any, ...]]:
    rows = []
    for chunk in range(chunks):
        path = team_scan.chunk_files(scan_dir, chunk).rows
        rows += [json.loads(line) for line in path.read_text().splitlines()]
    found = {r["key"]: (r["flavor"], r["sub_flavor"], r["verb"]) for r in rows}
    assert len(found) == len(rows), "a key was reported twice"
    return found


class _Stop(Exception):
    pass


class TestChunkScan(DivergenceFixturesMixin, ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scan_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.scan_root)

    def _build_team(self) -> dict[str, str]:
        """One key per flavor the ClickHouse phases must find."""
        fine = self._pg_person(version=1, distinct_ids=["fine-1"])
        self._ch_person(str(fine.uuid), 1, {"email": "pg@example.com"})
        self._ch_mapping("fine-1", str(fine.uuid), 0)
        stale = self._pg_person(version=1)
        self._ch_person(str(stale.uuid), 40, {"email": "old@example.com"})
        deleted = self._pg_person(version=2)
        tombstone_persons_in_postgres(self.team.pk, [deleted.uuid])
        self._ch_person(str(deleted.uuid), 7, {"email": "old@example.com"})
        new_owner = self._pg_person(version=1, distinct_ids=["moved"])
        self._ch_person(str(new_owner.uuid), 1, {"email": "pg@example.com"})
        ghost = str(uuid4())
        self._ch_person(ghost, 3, {"email": "ghost@example.com"})
        self._ch_mapping("moved", ghost, 5)
        self._ch_mapping("lost", ghost, 5)
        return {"stale": str(stale.uuid), "deleted": str(deleted.uuid), "ghost": ghost}

    def test_a_chunk_reports_each_clickhouse_flavor_with_its_verb(self):
        keys = self._build_team()
        scan_dir = self.scan_root / "scan"
        team_scan.create_plan(scan_dir, self.team.pk)

        cursor = team_scan.run_chunk(scan_dir, 0, resume=False)

        assert cursor.phase == team_scan.DONE
        assert _chunk_rows(scan_dir, 1) == {
            keys["stale"]: ("stale", None, "merge_stale"),
            keys["deleted"]: ("deleted_visible", None, "bury"),
            keys["ghost"]: ("ghost", "historical", None),
            "moved": ("diverged", "a_absent", "fold"),
            "lost": ("ghost", "owner_ghost", "restore"),
        }
        with pytest.raises(team_scan.ScanError, match="pass resume"):
            team_scan.run_chunk(scan_dir, 0, resume=False)

    def test_chunked_paged_and_interrupted_scan_gives_the_same_rows_as_one_run(self):
        self._build_team()
        whole = self.scan_root / "whole"
        team_scan.create_plan(whole, self.team.pk)
        team_scan.run_chunk(whole, 0, resume=False)

        split = self.scan_root / "split"
        plan = team_scan.create_plan(split, self.team.pk, chunks=3, ch_page_rows=2)
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
        for chunk in range(3):
            team_scan.run_chunk(split, chunk, resume=True)

        assert _chunk_rows(split, 3) == _chunk_rows(whole, 1)
        assert len(_chunk_rows(whole, 1)) == 5

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
