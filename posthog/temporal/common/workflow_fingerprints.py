"""Command-sequence fingerprints for long-running Temporal workflow definitions.

Temporal replays a workflow's recorded history against the current code whenever a
worker picks up an in-flight execution. If the code now issues a different command
sequence (an activity or child workflow added, removed, or reordered, or a child
workflow id changed), replay fails with NondeterminismError and the execution wedges
in Running — unprocessable, retrying forever — unless the change is gated with
``workflow.patched()``. For workflows that run for days or weeks this is guaranteed
to hit in-flight executions.

This module extracts, per ``@workflow.defn`` class, the source-ordered sequence of
command-issuing calls (activities, child workflows, timers) plus ``workflow.patched()``
/ ``workflow.deprecate_patch()`` markers. ``test_workflow_fingerprints.py`` compares
the result for each registered file against the committed baseline
(``workflow_fingerprints.json``), so a replay-breaking edit can't land unnoticed:
the test fails until the baseline is regenerated, and the failure message walks
through the ``workflow.patched()`` requirement.

After an intentional, properly gated change, regenerate the baseline with:

    python posthog/temporal/common/workflow_fingerprints.py

To enroll another long-running workflow file, add its repo-relative path to
``REGISTERED_WORKFLOW_FILES`` and regenerate. See
``.agents/skills/versioning-temporal-workflows/SKILL.md`` for the full workflow.

Stdlib-only on purpose: it must run as a plain script and stay importable without
Django or the temporal SDK.
"""

import ast
import json
from pathlib import Path

# Long-running workflows whose in-flight executions span worker deploys. Teams opt
# their files in here; every `@workflow.defn` class in a registered file is guarded.
REGISTERED_WORKFLOW_FILES: tuple[str, ...] = (
    "products/warehouse_sources/backend/temporal/data_imports/external_data_job.py",
    "products/warehouse_sources/backend/temporal/data_imports/cdc/workflows.py",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = Path(__file__).resolve().parent / "workflow_fingerprints.json"

# Calls that make the workflow issue a command (or mark a patch point). Matched by
# attribute or bare name so both `workflow.execute_activity(...)` and directly
# imported `start_child_workflow(...)` are caught.
_COMMAND_CALL_NAMES = frozenset(
    {
        "execute_activity",
        "start_activity",
        "execute_activity_method",
        "start_activity_method",
        "execute_local_activity",
        "start_local_activity",
        "execute_local_activity_method",
        "start_local_activity_method",
        "execute_child_workflow",
        "start_child_workflow",
        "sleep",
        "continue_as_new",
        "patched",
        "deprecate_patch",
    }
)

_CHILD_WORKFLOW_CALL_NAMES = frozenset({"execute_child_workflow", "start_child_workflow"})


def _command_call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute) and func.attr in _COMMAND_CALL_NAMES:
        return func.attr
    if isinstance(func, ast.Name) and func.id in _COMMAND_CALL_NAMES:
        return func.id
    return None


def _call_target(call: ast.Call) -> str:
    if call.args:
        return ast.unparse(call.args[0])
    for keyword in call.keywords:
        # `start_child_workflow(workflow="...")` / `execute_activity(activity=...)`
        if keyword.arg in ("workflow", "activity"):
            return ast.unparse(keyword.value)
    return ""


def _child_workflow_id(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "id":
            return ast.unparse(keyword.value)
    return None


def _workflow_defn_name(class_def: ast.ClassDef) -> str | None:
    """Return the workflow name if the class is decorated with `@workflow.defn`, else None."""
    for decorator in class_def.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call is not None else decorator
        is_defn = (isinstance(target, ast.Attribute) and target.attr == "defn") or (
            isinstance(target, ast.Name) and target.id == "defn"
        )
        if not is_defn:
            continue
        if call is not None:
            for keyword in call.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
        return class_def.name
    return None


def _fingerprint_class(class_def: ast.ClassDef) -> list[str]:
    entries: list[tuple[int, int, str]] = []
    for node in ast.walk(class_def):
        if not isinstance(node, ast.Call):
            continue
        name = _command_call_name(node.func)
        if name is None:
            continue
        entry = f"{name}({_call_target(node)})"
        if name in _CHILD_WORKFLOW_CALL_NAMES:
            child_id = _child_workflow_id(node)
            if child_id is not None:
                entry += f" id={child_id}"
        entries.append((node.lineno, node.col_offset, entry))
    return [entry for _, _, entry in sorted(entries, key=lambda item: (item[0], item[1]))]


def extract_fingerprints(source: str) -> dict[str, list[str]]:
    """Map workflow name -> source-ordered command entries, for every `@workflow.defn` class."""
    module = ast.parse(source)
    fingerprints: dict[str, list[str]] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef):
            workflow_name = _workflow_defn_name(node)
            if workflow_name is not None:
                fingerprints[workflow_name] = _fingerprint_class(node)
    return fingerprints


def compute_registered_fingerprints(repo_root: Path) -> dict[str, dict[str, list[str]]]:
    return {
        relative_path: extract_fingerprints((repo_root / relative_path).read_text())
        for relative_path in REGISTERED_WORKFLOW_FILES
    }


def main() -> None:
    baseline = compute_registered_fingerprints(REPO_ROOT)
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {BASELINE_PATH.relative_to(REPO_ROOT)}")  # noqa: T201


if __name__ == "__main__":
    main()
