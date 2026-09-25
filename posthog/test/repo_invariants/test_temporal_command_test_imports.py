import sys
import subprocess
from pathlib import Path

# A clean interpreter: pytest has already imported the test tree, so this process cannot tell
# which import pulled a test module in.
_SNAPSHOT = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()

import sys
from pathlib import Path

baseline = set(sys.modules)

import posthog.management.commands.start_temporal_worker
import posthog.management.commands.start_temporal_workflow
import posthog.management.commands.execute_temporal_workflow

repo_root = Path(sys.argv[1])


def is_test_file(module):
    path = getattr(module, "__file__", None)
    if path is None:
        return False
    try:
        relative = Path(path).relative_to(repo_root)
    except ValueError:
        return False
    if relative.parts[0].startswith("."):
        return False
    return "tests" in relative.parts[:-1]


pulled = sorted(
    name for name in set(sys.modules) - baseline if is_test_file(sys.modules[name])
)
print(",".join(pulled))
"""


def test_temporal_commands_do_not_import_test_packages() -> None:
    repo_root = Path(__file__).parents[3]
    result = subprocess.run(
        [sys.executable, "-c", _SNAPSHOT, str(repo_root)], capture_output=True, text=True, timeout=300
    )

    assert result.returncode == 0, f"import failed:\n{result.stderr[-2000:]}"
    assert result.stdout.strip() == "", (
        "The Temporal management commands imported these test modules at module scope: "
        f"{result.stdout.strip()}. Every Temporal worker runs this import path, so a runtime "
        "image that ships without the test files cannot start any worker. Keep the shared code "
        "in a regular package, such as posthog/temporal/waiter/."
    )
