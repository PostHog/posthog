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


# A builtin not implemented by every VM forks the cross-language surface, so the set is a
# deliberate, reviewed allowlist. Implement a new function in all three VMs instead of growing it;
# a change here needs a justification in the PR.
def test_partial_implementations_are_a_deliberate_allowlist() -> None:
    spec = json.loads(SPEC_PATH.read_text())["functions"]
    partial = {name: sorted(entry["implementations"]) for name, entry in spec.items() if "implementations" in entry}
    assert partial == {
        "extract": ["python", "typescript"],
        "max2": ["python", "rust"],
        "print": ["python", "typescript"],
        "run": ["python"],
        "tryBase64Decode": ["rust", "typescript"],
    }
