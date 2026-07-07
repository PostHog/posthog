import json
import difflib
import textwrap

import pytest

from posthog.temporal.common.workflow_fingerprints import (
    BASELINE_PATH,
    REGISTERED_WORKFLOW_FILES,
    REPO_ROOT,
    compute_registered_fingerprints,
    extract_fingerprints,
)

REGENERATE_COMMAND = "python posthog/temporal/common/workflow_fingerprints.py"
SKILL_POINTER = ".agents/skills/versioning-temporal-workflows/SKILL.md"


def test_extractor_captures_command_sequence() -> None:
    source = textwrap.dedent(
        """
        import asyncio

        from temporalio import workflow
        from temporalio.workflow import start_child_workflow


        @workflow.defn(name="my-workflow")
        class MyWorkflow:
            @workflow.run
            async def run(self, inputs):
                await workflow.execute_activity(first_activity, inputs)
                if workflow.patched("use-v2-path"):
                    await workflow.execute_activity(second_activity_v2, inputs)
                else:
                    await workflow.execute_activity(second_activity, inputs)
                await asyncio.sleep(60)
                await start_child_workflow(workflow="child-by-name", id=f"child-{inputs.job_id}")
                await workflow.start_child_workflow(ChildWorkflow.run, inputs, id="fixed-id")


        class NotAWorkflow:
            async def run(self):
                await workflow.execute_activity(ignored_activity)
        """
    )

    assert extract_fingerprints(source) == {
        "my-workflow": [
            "execute_activity(first_activity)",
            "patched('use-v2-path')",
            "execute_activity(second_activity_v2)",
            "execute_activity(second_activity)",
            "sleep(60)",
            "start_child_workflow('child-by-name') id=f'child-{inputs.job_id}'",
            "start_child_workflow(ChildWorkflow.run) id='fixed-id'",
        ]
    }


def test_fingerprints_match_committed_baseline() -> None:
    for relative_path in REGISTERED_WORKFLOW_FILES:
        assert (REPO_ROOT / relative_path).exists(), (
            f"{relative_path} is registered in REGISTERED_WORKFLOW_FILES but does not exist. "
            f"If the file moved, update the registry in posthog/temporal/common/workflow_fingerprints.py "
            f"and regenerate the baseline with `{REGENERATE_COMMAND}`."
        )

    computed = compute_registered_fingerprints(REPO_ROOT)

    for relative_path, workflows in computed.items():
        assert workflows, (
            f"{relative_path} is registered but no `@workflow.defn` class was found in it — "
            f"the guard would be vacuous. Update REGISTERED_WORKFLOW_FILES in "
            f"posthog/temporal/common/workflow_fingerprints.py."
        )

    baseline = json.loads(BASELINE_PATH.read_text())
    if computed == baseline:
        return

    diff_sections: list[str] = []
    added_patch_marker = False
    for relative_path in sorted(set(baseline) | set(computed)):
        baseline_workflows = baseline.get(relative_path, {})
        computed_workflows = computed.get(relative_path, {})
        if baseline_workflows == computed_workflows:
            continue
        for workflow_name in sorted(set(baseline_workflows) | set(computed_workflows)):
            old = baseline_workflows.get(workflow_name, [])
            new = computed_workflows.get(workflow_name, [])
            if old == new:
                continue
            diff = "\n".join(
                difflib.unified_diff(old, new, fromfile="committed baseline", tofile="your change", lineterm="")
            )
            diff_sections.append(f"{relative_path} :: {workflow_name}\n{diff}")
            added_patch_marker = added_patch_marker or any(
                line.startswith("patched(") or line.startswith("deprecate_patch(") for line in set(new) - set(old)
            )

    patch_note = (
        "New workflow.patched()/deprecate_patch() markers detected — if every changed command path "
        "is gated by them, this change is safe to land."
        if added_patch_marker
        else "No new workflow.patched() marker detected. Unless this workflow has no in-flight executions, "
        "gate the change before landing it."
    )

    pytest.fail(
        "The scheduled-command sequence of a long-running Temporal workflow changed.\n\n"
        "In-flight executions of these workflows replay their recorded history against the new code; "
        "a changed command sequence fails replay with NondeterminismError and wedges the execution in "
        "Running (this blocked all external data syncs on 2026-07-01). Adding, removing, or reordering "
        "activity/child-workflow/timer calls — or changing a child workflow id — must be gated with "
        f"workflow.patched(). See {SKILL_POINTER} and posthog/temporal/README.md.\n\n"
        f"{patch_note}\n\n"
        f"Once the change is correctly gated (or the workflow is new), regenerate the baseline with:\n"
        f"    {REGENERATE_COMMAND}\n\n" + "\n\n".join(diff_sections)
    )
