import os
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("resolve-changed-files.sh")
BASE = "a" * 40
HEAD = "b" * 40


def run_resolver(
    tmp_path: Path,
    response: dict[str, object],
    target: str,
    paths: list[str],
    fail_fetch: bool = False,
    fail_api: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    (tmp_path / "compare-response.json").write_text(json.dumps(response))
    (tmp_path / "diff-paths").write_text("\n".join(paths) + "\n")
    for name, body in {
        "gh": """echo "$*" > "$RUNNER_TEMP/api-call"
if [ "$FAIL_API" = true ]; then
    echo '(HTTP 403)' >&2
    exit 1
fi
cat "$RUNNER_TEMP/compare-response.json"
""",
        "git": """case "$1" in
    rev-parse) echo "$HEAD_SHA" ;;
    fetch)
        echo "$*" > "$RUNNER_TEMP/fetch-call"
        [ "$FAIL_FETCH" != true ] ;;
    diff)
        [ "$*" = "diff --name-only --no-renames $BASE_SHA HEAD" ] || exit 1
        cat "$RUNNER_TEMP/diff-paths" ;;
    *) exit 1 ;;
esac
""",
    }.items():
        executable = tmp_path / name
        executable.write_text("#!/usr/bin/env bash\n" + body)
        executable.chmod(0o755)
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
            "REPOSITORY": "example/repo",
            "MERGE_TARGET": target,
            "HEAD_SHA": HEAD,
            "BASE_SHA": BASE,
            "FAIL_FETCH": str(fail_fetch).lower(),
            "FAIL_API": str(fail_api).lower(),
        },
        capture_output=True,
        text=True,
    )
    return result, output.read_text()


@pytest.mark.parametrize("target", ["stack-parent", "master", "c" * 40])
@pytest.mark.parametrize("file_count", [2, 300])
def test_complete_paths_and_event_base(tmp_path: Path, target: str, file_count: int) -> None:
    paths = ["rust/old/src/lib.rs", "rust/new/src/lib.rs", "rust/deleted/Cargo.toml", "rust/Cargo.lock"]
    response: dict[str, object] = {
        "merge_base_commit": {"sha": BASE},
        "files": [
            {"filename": paths[1], "previous_filename": paths[0]},
            {"filename": paths[2]},
        ],
    }
    if file_count == 300:
        response["files"] = [{"filename": f"rust/file-{i}"} for i in range(300)]
    else:
        paths = paths[:3]
    result, outputs = run_resolver(tmp_path, response, target, paths)
    assert result.returncode == 0
    assert "resolved=true" in outputs
    assert f"merge_base={BASE}" in outputs
    assert (tmp_path / "changed-files.txt").read_text().splitlines() == sorted(paths)
    assert f"compare/{target}...{HEAD}?per_page=1" in (tmp_path / "api-call").read_text()
    assert (tmp_path / "fetch-call").exists() == (file_count == 300)


@pytest.mark.parametrize(
    "response,fail_fetch,fail_api,target",
    [
        ({"merge_base_commit": {"sha": "invalid"}, "files": []}, False, False, "master"),
        ({"merge_base_commit": {"sha": BASE}}, False, False, "master"),
        ({"merge_base_commit": {"sha": BASE}, "files": [{}] * 300}, True, False, "master"),
        ({}, False, True, "master"),
        ({}, False, False, "0" * 40),
        ({}, False, False, ""),
    ],
)
def test_uncertain_diff_does_not_publish_a_partial_list(
    tmp_path: Path, response: dict[str, object], fail_fetch: bool, fail_api: bool, target: str
) -> None:
    result, outputs = run_resolver(tmp_path, response, target, [], fail_fetch, fail_api)
    assert result.returncode == 0
    assert outputs.strip() == "resolved=false"
    assert not (tmp_path / "changed-files.txt").exists()


def test_truncated_compare_uses_only_endpoint_trees(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    def git(*args: str, cwd: Path = source) -> str:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (source / "old.rs").write_text("unchanged contents\n")
    (source / "deleted.rs").write_text("deleted contents\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("mv", "old.rs", "new.rs")
    git("rm", "deleted.rs")
    (source / "Cargo.lock").write_text("lockfile\n")
    git("add", ".")
    git("commit", "-qm", "change")
    expected = set(git("diff", "--name-only", "--no-renames", f"{base}...HEAD").splitlines())
    shallow = tmp_path / "shallow"
    git("clone", "-q", "--depth=1", source.as_uri(), str(shallow))
    assert git("rev-parse", "--is-shallow-repository", cwd=shallow) == "true"
    response = {"merge_base_commit": {"sha": base}, "files": [{}] * 300}
    (tmp_path / "response.json").write_text(json.dumps(response))
    executable = tmp_path / "gh"
    executable.write_text('#!/usr/bin/env bash\ncat "$RUNNER_TEMP/response.json"\n')
    executable.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPT.resolve())],
        cwd=shallow,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "REPOSITORY": "example/repo",
            "MERGE_TARGET": "stack-parent",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert "resolved=true" in (tmp_path / "output").read_text(), result.stdout
    assert set((tmp_path / "changed-files.txt").read_text().splitlines()) == expected
