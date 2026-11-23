import sys
import importlib.util
from pathlib import Path

from django.conf import global_settings

REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTION_PATH = REPO_ROOT / "tools" / "snob_backend_test_selection_shadow.py"


def _load_selection():
    spec = importlib.util.spec_from_file_location("snob_backend_test_selection_shadow", SELECTION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_selection_blocklist_covers_every_django_global_setting():
    installed = {name for name in dir(global_settings) if name.isupper()}
    missing = sorted(installed - _load_selection().DJANGO_GLOBAL_SETTINGS)
    assert not missing, (
        "tools/snob_backend_test_selection_shadow.py DJANGO_GLOBAL_SETTINGS is missing settings the "
        f"installed Django reads: {missing}. Add them so a PR that sets one runs the full backend matrix."
    )
