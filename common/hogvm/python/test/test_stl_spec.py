import json
from pathlib import Path

from common.hogvm.python.stl import STL

SPEC_PATH = Path(__file__).parents[2] / "spec" / "stl.json"
ALL_VMS = ["python", "typescript", "rust"]


# Importing the STL already fails when a Python builtin is missing from the spec; this covers the
# other direction — a spec function marked as implemented here but absent.
def test_every_spec_function_marked_python_is_implemented() -> None:
    spec = json.loads(SPEC_PATH.read_text())["functions"]
    missing = sorted(
        name for name, entry in spec.items() if "python" in entry.get("implementations", ALL_VMS) and name not in STL
    )
    assert missing == []
