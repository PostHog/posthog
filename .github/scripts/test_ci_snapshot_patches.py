import os
import textwrap
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("engine", [".github", ".depot"])
@pytest.mark.parametrize("conflict", [False, True], ids=["overlapping-patches", "conflicting-patches"])
def test_snapshot_patches_skip_applied_files_but_reject_conflicts(engine: str, conflict: bool, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True)

    git("init", "-q")
    for name in ("a.snap", "b.snap"):
        (repo / name).write_text("old\n")
    git("add", ".")
    git(
        "-c",
        "user.name=CI fixture",
        "-c",
        "user.email=ci@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "fixture",
    )
    for name in ("a.snap", "b.snap"):
        (repo / name).write_text("new\n")
    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "shard.patch").write_text(git("diff"))
    git("checkout", "--", ".")
    (repo / "a.snap").write_text("conflicting\n" if conflict else "new\n")
    git("add", "a.snap")

    action = (ROOT / engine / "actions/commit-snapshots/action.yml").read_text()
    step = action.split("- name: Apply snapshot patches\n", 1)[1].split("\n        - name:", 1)[0]
    script = textwrap.dedent(step.split("run: |\n", 1)[1])
    result = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", script],
        cwd=repo,
        env={**os.environ, "PATCH_PATH": str(patches)},
        capture_output=True,
        text=True,
    )
    if conflict:
        assert result.returncode != 0
        assert "could not be applied" in result.stdout
        assert (repo / "a.snap").read_text() == "conflicting\n"
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert (repo / "a.snap").read_text() == "new\n"
        assert (repo / "b.snap").read_text() == "new\n"
