import os
import subprocess
from pathlib import Path

import unittest


class TestRenderHobbyCompose(unittest.TestCase):
    def test_deployment_values_preserve_container_variables(self) -> None:
        renderer = Path(__file__).resolve().parents[1] / "helpers" / "render-hobby-compose.sh"
        deployment = {
            "DOMAIN": "example.com",
            "POSTHOG_SECRET": "example-secret",
            "ENCRYPTION_SALT_KEYS": "example-salt",
            "REGISTRY_URL": "example/posthog",
            "POSTHOG_APP_TAG": "example-tag",
            "TLS_BLOCK": "tls internal",
        }
        container_script = """TIMEOUT=60
ELAPSED=0
ELAPSED=$$((ELAPSED + 2))
[ $$ELAPSED -lt $$TIMEOUT ] || exit 1
TOPICS="example_events example_logs"
for topic in $$TOPICS; do
    printf '%s\n' "$$topic"
done
printf '%s\n' "$${ELAPSED}s"
"""
        deployment_template = "\n".join("${" + key + "}" for key in deployment) + "\n"
        compose_default = "${OPTIONAL_SETTING:-fallback}\n"
        for polluted in (False, True):
            with self.subTest(exported_container_variables=polluted):
                env = {"PATH": os.environ["PATH"], **deployment}
                if polluted:
                    env.update(dict.fromkeys(("TOPICS", "topic", "ELAPSED", "TIMEOUT"), "unexpected"))
                rendered = subprocess.run(
                    ["bash", str(renderer)],
                    input=deployment_template + compose_default + container_script,
                    text=True,
                    capture_output=True,
                    check=True,
                    env=env,
                ).stdout
                self.assertEqual(
                    rendered,
                    "\n".join(deployment.values()) + "\n" + compose_default + container_script,
                )
                command = rendered.split(compose_default, 1)[1].replace("$$", "$")
                result = subprocess.run(["sh", "-c", command], text=True, capture_output=True, check=True, env=env)
                self.assertEqual(result.stdout.splitlines(), ["example_events", "example_logs", "2s"])
