#!/usr/bin/env python3

import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import unittest

from parameterized import parameterized

SCRIPT = Path(__file__).resolve().parents[1] / "ci-wait-for-docker"

# Stands in for `docker compose`: the first `up` fails without creating anything, like a
# launch that dies in the background. Every later `up` creates the services it names.
FAKE_DOCKER = """#!/usr/bin/env bash
shift
while [ "$1" = "-f" ]; do shift 2; done
command=$1
shift
case "$command" in
    up)
        shift
        if [ ! -f "$STATE/launch-failed" ]; then touch "$STATE/launch-failed"; exit 1; fi
        for service in "$@"; do touch "$STATE/service-$service"; done
        echo "$*" >> "$STATE/retries"
        ;;
    ps) [ -f "$STATE/service-$2" ] && echo "container-$2" ;;
esac
exit 0
"""

FAKE_WAIT_FOR_DOCKER = """#!/usr/bin/env bash
[ "$1" = "--only" ] && shift
for service in "$@"; do [ -f "$STATE/service-$service" ] || exit 1; done
"""


class TestCiWaitForDockerRetry(unittest.TestCase):
    @parameterized.expand(
        [
            ("launched_services_are_restarted", ["db", "temporal", "elasticsearch"], "db temporal elasticsearch"),
            ("no_service_list_restarts_waited_services", [], "db"),
        ]
    )
    def test_retry_after_dead_launch(self, _name: str, launched: list[str], expected_retry: str) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir()
            (root / "fake").mkdir()
            (root / "state").mkdir()
            (root / "docker-compose.dev.yml").touch()
            shutil.copy(SCRIPT, root / "bin" / "ci-wait-for-docker")
            (root / "bin" / "wait-for-docker").write_text(FAKE_WAIT_FOR_DOCKER)
            (root / "fake" / "docker").write_text(FAKE_DOCKER)
            for executable in [root / "bin" / "wait-for-docker", root / "fake" / "docker"]:
                executable.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{root / 'fake'}:{os.environ['PATH']}",
                "STATE": str(root / "state"),
                "TMPDIR": tmp,
                "WAIT_FOR_DOCKER_TIMEOUT": "1",
            }
            env.pop("COMPOSE_FILE", None)
            env.pop("COMPOSE_PROFILES", None)
            script = str(root / "bin" / "ci-wait-for-docker")

            subprocess.run([script, "launch", "--background", *launched], env=env, check=True, timeout=30)
            subprocess.run([script, "wait", "--only", "db"], env=env, check=True, timeout=30)

            self.assertEqual((root / "state" / "retries").read_text().strip(), expected_retry)


if __name__ == "__main__":
    unittest.main()
