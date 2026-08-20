import sys
import subprocess

# A clean interpreter: pytest has already imported half the world, so this process cannot tell
# which import pulled the package in.
_SNAPSHOT = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
import posthog.temporal.health_checks.processing
from posthog.temporal.health_checks.registry import ensure_registry_loaded
ensure_registry_loaded()
import sys
print("posthog.dags" in sys.modules)
"""


def test_health_check_processing_does_not_import_the_dagster_package() -> None:
    result = subprocess.run([sys.executable, "-c", _SNAPSHOT], capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, f"import failed:\n{result.stderr[-2000:]}"
    assert result.stdout.strip() == "False", (
        "Importing the Temporal health checks pulled in posthog.dags, whose __init__ runs "
        "django.setup(). That re-applies LOGGING, and disable_existing_loggers turns off every "
        "logger built before it. Import shared symbols such as JobOwners from posthog.job_owners."
    )
