import os
import functools
import subprocess
from pathlib import Path

import pytest

import yaml

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = "posthog/clickhouse/migrations"
MIGRATION_TEMPLATE = """from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.cluster import NodeRole

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE {table} ADD COLUMN IF NOT EXISTS example String",
        node_roles=[NodeRole.DATA],
    ),
]
"""
OWN = f"{MIGRATIONS}/0003_own.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit_file(repo: Path, name: str, content: str) -> str:
    path = repo / MIGRATIONS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture")
    return git(repo, "rev-parse", "HEAD")


def commit_on_master(repo: Path, master: str, name: str, content: str) -> None:
    git(repo, "checkout", "-q", "master")
    commit_file(repo, name, content)
    git(repo, "update-ref", f"refs/remotes/{master}", "HEAD")
    git(repo, "checkout", "-q", "topic")


@functools.cache
def list_step(engine: str) -> str:
    workflow = yaml.safe_load((ROOT / engine / "workflows/ci-backend.yml").read_text())
    return next(
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "List this PR's ClickHouse migrations"
    )


@pytest.mark.parametrize("engine,master", [(".github", "origin/master"), (".depot", "upstream/master")])
@pytest.mark.parametrize(
    "case,expected",
    [
        ("based on master", ([OWN], [OWN])),
        ("stale base", ([OWN], [OWN])),
        ("stale base carries master's migration", ([], [])),
        ("master adds a similar migration later", ([OWN], [OWN])),
        ("master edits a migration the branch carries", ([], [f"{MIGRATIONS}/0002_master.py"])),
        ("edits an existing migration", ([], [f"{MIGRATIONS}/0001_base.py"])),
        ("base missing from the clone", ([f"{MIGRATIONS}/0004_own.py"], [f"{MIGRATIONS}/0004_own.py"])),
        ("unknown base", None),
        ("no master ref", None),
    ],
)
def test_lists_only_this_prs_migrations(
    engine: str,
    master: str,
    case: str,
    expected: tuple[list[str], list[str]] | None,
    tmp_path: Path,
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
    git(repo, "checkout", "-qb", "topic")

    if case == "based on master":
        base = git(repo, "rev-parse", "HEAD")
        commit_file(repo, "0003_own.py", "own\n")
    elif case == "stale base":
        commit_file(repo, "0003_own.py", "own\n")
    elif case == "master adds a similar migration later":
        commit_on_master(repo, master, "0003_master.py", MIGRATION_TEMPLATE.format(table="master_table"))
        commit_file(repo, "0003_own.py", MIGRATION_TEMPLATE.format(table="own_table"))
    elif case == "master edits a migration the branch carries":
        commit_on_master(repo, master, "0002_master.py", "master fixed\n")
    elif case == "edits an existing migration":
        commit_file(repo, "0001_base.py", "modified\n")
    elif case == "base missing from the clone":
        base = commit_file(repo, "0003_lower_layer.py", "lower\n")
        commit_file(repo, "0004_own.py", "own\n")
        source = tmp_path / "upstream.git"
        repo.rename(source)
        subprocess.run(
            ["git", "clone", "-q", "--depth=1", "--no-single-branch", "-b", "topic", source.as_uri(), str(repo)],
            check=True,
        )
        if engine == ".depot":
            git(repo, "update-ref", f"refs/remotes/{master}", "refs/remotes/origin/master")
            git(repo, "remote", "remove", "origin")
    elif case == "unknown base":
        base = "0" * 40
    elif case == "no master ref":
        git(repo, "update-ref", "-d", f"refs/remotes/{master}")

    result = subprocess.run(
        ["bash", "-e", "-c", list_step(engine)],
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
    if expected is None:
        assert result.returncode != 0
        return
    assert result.returncode == 0, result.stderr
    added = (tmp_path / "ch-migrations-added.txt").read_text().splitlines()
    changed = (tmp_path / "ch-migrations-changed.txt").read_text().splitlines()
    assert (added, changed) == expected
