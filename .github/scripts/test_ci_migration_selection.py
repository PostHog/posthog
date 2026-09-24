import os
import textwrap
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = "posthog/clickhouse/migrations"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit_file(repo: Path, name: str, content: str) -> str:
    path = repo / MIGRATIONS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture")
    return git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("engine,master", [(".github", "origin/master"), (".depot", "upstream/master")])
@pytest.mark.parametrize(
    "case", ["plain", "stale", "own", "collision", "modified", "missing-base", "bad-base", "bad-master"]
)
def test_selects_only_pr_migrations_and_fails_on_invalid_refs(
    engine: str, master: str, case: str, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.name", "CI fixture")
    git(repo, "config", "user.email", "ci@example.com")
    git(repo, "config", "commit.gpgsign", "false")
    base = commit_file(repo, "0001_base.py", "base\n")
    commit_file(repo, "0002_master.py", "master\n")
    git(repo, "update-ref", f"refs/remotes/{master}", "HEAD")
    if case == "plain":
        base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "topic")
    if case == "missing-base":
        source = tmp_path / "upstream.git"
        repo.rename(source)
        subprocess.run(["git", "clone", "-q", "--depth=1", source.as_uri(), str(repo)], check=True)
        git(repo, "update-ref", f"refs/remotes/{master}", "HEAD")
        if engine == ".depot":
            git(repo, "remote", "remove", "origin")
    expected_added: list[str] = []
    expected_changed: list[str] = []
    if case in ("own", "plain"):
        commit_file(repo, "0003_own.py", "own\n")
        expected_added = expected_changed = [f"{MIGRATIONS}/0003_own.py"]
    elif case == "collision":
        commit_file(repo, "0002_master.py", "conflict\n")
        expected_added = expected_changed = [f"{MIGRATIONS}/0002_master.py"]
    elif case == "modified":
        commit_file(repo, "0001_base.py", "modified\n")
        expected_changed = [f"{MIGRATIONS}/0001_base.py"]
    elif case == "bad-base":
        base = "0" * 40
    elif case == "bad-master":
        git(repo, "update-ref", "-d", f"refs/remotes/{master}")

    workflow = (ROOT / engine / "workflows/ci-backend.yml").read_text()
    step = workflow.split("- name: List this PR's ClickHouse migrations\n", 1)[1].split("\n\n", 1)[0]
    script = textwrap.dedent(step.split("run: |\n", 1)[1])
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env={
            **os.environ,
            "BASE_SHA": base,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_SERVER_URL": str(tmp_path),
            "GITHUB_REPOSITORY": "upstream.git",
        },
        text=True,
        capture_output=True,
    )
    if case.startswith("bad-"):
        assert result.returncode != 0
        return
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "ch-migrations-added.txt").read_text().splitlines() == expected_added
    assert (tmp_path / "ch-migrations-changed.txt").read_text().splitlines() == expected_changed
