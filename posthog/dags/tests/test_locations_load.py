import os
import sys
import subprocess
from pathlib import Path

import pytest

_LOCATIONS_DIR = Path(__file__).parent.parent / "locations"
_REPO_ROOT = Path(__file__).parents[3]
_LOCATION_MODULES = sorted(p.stem for p in _LOCATIONS_DIR.glob("*.py") if p.stem != "__init__")


@pytest.mark.parametrize("location", _LOCATION_MODULES)
def test_code_location_loads_in_fresh_interpreter(location: str) -> None:
    snippet = (
        "import django; django.setup(); import importlib; "
        f"m = importlib.import_module('posthog.dags.locations.{location}'); "
        "assert m.defs is not None"
    )
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "posthog.settings", "TEST": "1"}
    env.pop("DEBUG", None)
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        env=env,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"code location {location!r} failed to load:\n{result.stderr[-5000:]}"
