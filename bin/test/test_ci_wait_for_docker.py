import os
import shutil
import subprocess
from pathlib import Path


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def test_wait_retries_the_complete_original_launch(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bin_dir = repo_root / "bin"
    fake_bin = tmp_path / "fake-bin"
    bin_dir.mkdir(parents=True)
    fake_bin.mkdir()

    shutil.copy2(Path(__file__).parents[1] / "ci-wait-for-docker", bin_dir)
    _write_executable(
        bin_dir / "wait-for-docker",
        r"""#!/usr/bin/env bash
count_file="$TMPDIR/wait-count"
count=$(cat "$count_file" 2>/dev/null || echo 0)
count=$((count + 1))
printf '%s\n' "$count" > "$count_file"
[ "$count" -gt 1 ]
""",
    )
    _write_executable(
        fake_bin / "docker",
        r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DOCKER_CALLS"
""",
    )

    calls_file = tmp_path / "docker-calls"
    env = {
        **os.environ,
        "DOCKER_CALLS": str(calls_file),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "TMPDIR": str(tmp_path),
        "WAIT_FOR_DOCKER_RETRIES": "1",
        "WAIT_FOR_DOCKER_RETRY_TIMEOUT": "0",
        "WAIT_FOR_DOCKER_TIMEOUT": "0",
    }

    subprocess.run(
        [bin_dir / "ci-wait-for-docker", "launch", "--background", "db", "objectstorage", "temporal"],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )
    result = subprocess.run(
        [bin_dir / "ci-wait-for-docker", "wait", "objectstorage"],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )

    compose_up_calls = [line for line in calls_file.read_text().splitlines() if " up -d" in line]
    assert compose_up_calls == [
        f"compose -f {repo_root}/docker-compose.dev.yml up -d db objectstorage temporal",
        f"compose -f {repo_root}/docker-compose.dev.yml up -d db objectstorage temporal",
    ]
    assert "re-running docker compose up for the original launch: db objectstorage temporal" in result.stdout
