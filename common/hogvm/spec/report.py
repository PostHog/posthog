# Renders a markdown report of the differences between two versions of the HogVM STL contract
# (common/hogvm/spec/stl.json). Hog CI runs it on pull requests that change the contract and
# posts the output as a sticky PR comment. Prints nothing when the contracts are equal.
#
# Stdlib only, run as a file (not a module): CI invokes it from a sparse checkout before any
# dependency setup.
#
#   python3 common/hogvm/spec/report.py <base-stl.json> <head-stl.json>

import sys
import json
from typing import Any

ALL_VMS = ["python", "typescript", "rust"]


def describe(entry: dict[str, Any]) -> str:
    if entry["maxArgs"] is None:
        arity = f"{entry['minArgs']}+ args"
    elif entry["maxArgs"] == entry["minArgs"]:
        arity = f"{entry['minArgs']} arg" + ("s" if entry["minArgs"] != 1 else "")
    else:
        arity = f"{entry['minArgs']}-{entry['maxArgs']} args"
    impls = entry.get("implementations", ALL_VMS)
    vms = "all VMs" if impls == ALL_VMS else ", ".join(impls)
    return f"{arity} ({vms})"


def render_report(base: dict[str, Any], head: dict[str, Any]) -> str:
    base_fns: dict[str, Any] = base["functions"]
    head_fns: dict[str, Any] = head["functions"]

    rows = []
    for name in sorted(set(base_fns) | set(head_fns)):
        if name not in base_fns:
            rows.append(f"| `{name}` | added | | {describe(head_fns[name])} |")
        elif name not in head_fns:
            rows.append(f"| `{name}` | removed | {describe(base_fns[name])} | |")
        elif describe(base_fns[name]) != describe(head_fns[name]):
            rows.append(f"| `{name}` | changed | {describe(base_fns[name])} | {describe(head_fns[name])} |")

    if not rows:
        return ""

    return "\n".join(
        [
            "## HogVM STL contract changes",
            "",
            "This PR changes `common/hogvm/spec/stl.json`, the contract every HogVM"
            " (Python, TypeScript, Rust) consumes. Review the rows below as behavior"
            " changes in all of them.",
            "",
            "| Function | Change | Before | After |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
            "Generated artifacts and conformance vectors come from"
            " `python -m common.hogvm.spec.compile`. See the `changing-hogvm` skill.",
            "",
        ]
    )


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as base_file:
        base_spec = json.load(base_file)
    with open(sys.argv[2], encoding="utf-8") as head_file:
        head_spec = json.load(head_file)
    sys.stdout.write(render_report(base_spec, head_spec))
