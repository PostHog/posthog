import os
import re
import json
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

    def test_object_storage_keys_come_from_env(self) -> None:
        compose = Path(__file__).resolve().parents[2] / "docker-compose.hobby.yml"
        # A default value would let an install start without keys of its own.
        references = re.findall(
            r"(?<!\$)\$\{(OBJECT_STORAGE_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY))([^}]*)\}", compose.read_text()
        )
        self.assertTrue(references)
        for name, modifier in references:
            self.assertTrue(modifier.startswith(":?"), f"${{{name}{modifier}}} must fail without the key")

        install_keys = {
            "OBJECT_STORAGE_ACCESS_KEY_ID": "install-access-key",
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": "install-secret-key",
        }
        # Ignore a local .env, so only the values below fill in the file.
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose), "--env-file", os.devnull, "config", "--format", "json"],
            text=True,
            capture_output=True,
            env={"PATH": os.environ["PATH"], **install_keys},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        for service in ("web", "objectstorage"):
            environment = services[service]["environment"]
            self.assertEqual({key: environment.get(key) for key in install_keys}, install_keys)
        # Services that extend docker-compose.base.yml also get the shared keys from .env.services,
        # unless the hobby file overrides them.
        shared = sorted(
            f"{name}: {key}"
            for name, service in services.items()
            for key, value in (service.get("environment") or {}).items()
            if "object_storage_root" in (value or "")
        )
        self.assertEqual(shared, [])
