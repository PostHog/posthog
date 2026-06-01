import sys
import subprocess

# Heavy subsystems that must NOT be imported by a bare ``django.setup()``. Each one was
# deliberately pulled off the startup path (lazy API router, deferred AI-core imports,
# deferred embedded-ClickHouse). Importing any of them at setup means a new module-level
# import re-opened a door — defer it (function-local / TYPE_CHECKING / lazy facade) instead
# of widening this budget. See logs/startup-profile and the PRs that introduced these cuts.
FORBIDDEN_AT_SETUP = [
    "posthog.api.rest_router",  # the 160-route DRF aggregator — builds lazily on first request
    "posthog.temporal.ai",  # AI temporal workflows -> ee.hogai chat-agent core
    "ee.hogai.chat_agent.graph",  # the assistant graph
    "ee.hogai.tools",  # the agent tool registry
    "chdb",  # embedded ClickHouse
]

# Runs in a clean interpreter: pytest has already imported half the world, so we cannot
# inspect this process's sys.modules. A subprocess gives a faithful cold-start snapshot.
_SNAPSHOT = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
import sys
print("\\n".join(sorted(m for m in sys.modules)))
"""


def test_django_setup_does_not_import_heavy_subsystems() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _SNAPSHOT],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"django.setup() failed:\n{result.stderr[-2000:]}"
    loaded = set(result.stdout.splitlines())

    offenders = [mod for mod in FORBIDDEN_AT_SETUP if mod in loaded or any(m.startswith(mod + ".") for m in loaded)]
    assert not offenders, (
        f"These heavy modules were imported by a bare django.setup(): {offenders}. "
        "Something added a module-level import that drags them onto the startup path "
        "(shell, migrate, celery, CI all pay for it). Defer the offending import instead."
    )
