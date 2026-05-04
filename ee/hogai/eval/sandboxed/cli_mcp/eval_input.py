"""Eval cases for the ``posthog:exec`` ``input`` parameter.

Two eval functions, one per payload-shape expectation:

* ``eval_input_structured`` — long, quote-heavy payloads (notebook,
  skill). The agent should reach for the structured ``input`` field;
  ``PreferredExecForm(prefer="structured")`` enforces this.
* ``eval_input_either`` — short payloads (dashboard, insight). Inline
  JSON and structured ``input`` both pass; the eval just confirms the
  call happened. ``PreferredExecForm(prefer="either")`` accepts either
  form.

Each case carries its target tool name in ``expected["target_tool"]``
so the shared ``CalledTargetTool`` and ``PreferredExecForm`` scorers
score 1.0/0.0 per case without fan-out across unrelated tools.

Skips when ``--mcp-mode=tools`` because the ``exec`` tool is only
registered in ``cli`` mode (see ``conftest.py:_apply_mcp_mode``).

To run:
    pytest ee/hogai/eval/sandboxed/cli_mcp/eval_input.py --mcp-mode=cli
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.cli_mcp.scorers import CalledTargetTool, PreferredExecForm
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero

NOTEBOOK_TOOL = "notebooks-create"
SKILL_TOOL = "llma-skill-create"
DASHBOARD_TOOL = "dashboard-create"
INSIGHT_TOOL = "insight-create"

NOTEBOOK_BODY = """# Q4 funnel investigation

We saw the **signup → first-event** funnel drop ~12% week-over-week starting Oct 14.
This notebook collects the queries we ran while triaging it.

## Hypothesis 1 — instrumentation regression

The new SDK release on Oct 13 might have stopped emitting `$identify` for users who
sign up via the "Continue with Google" flow. If so, those users would be missing from
the second funnel step.

```sql
SELECT count(*) FROM events
WHERE event = '$identify'
  AND properties.$lib_version = '1.227.0'
  AND timestamp >= '2024-10-13'
```

## Hypothesis 2 — onboarding copy change

PM rolled out new onboarding copy on Oct 14 reading "Let's get started!" — earlier copy
was 'Welcome aboard'. The funnel step "Completed first action" relies on a click event
attached to the CTA whose label changed in the same PR.
"""

SKILL_BODY = """---
name: triage-funnel-drop
description: Use when a user reports a sudden drop in a saved funnel insight.
---

# Triaging a funnel drop

When a user pings about a "funnel suddenly dropped", run these steps in order. Don't
guess — every check below is cheap and rules out a class of regressions.

## 1. Confirm the drop is real

```text
posthog:exec({ "command": "info insight-get" })
posthog:exec({ "command": "call insight-get", "input": { "id": <funnel_id> } })
```

Look at the funnel's `last_run_at` and the cached series. If the cache is stale the
"drop" might just be the latest data point being a partial day.

## 2. Check for SDK release correlation

A funnel drop that aligns with an SDK release is almost always an instrumentation
regression. Cross-reference the SDK version distribution:

```sql
SELECT properties.$lib_version, count(*)
FROM events WHERE timestamp >= now() - INTERVAL 14 DAY
GROUP BY properties.$lib_version ORDER BY count() DESC
```
"""


@pytest.mark.django_db
async def eval_input_structured(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    """Long, quote-heavy payloads — agent must use the structured ``input`` field."""
    if mcp_mode == "tools":
        pytest.skip("posthog:exec input field only exists in cli mode")

    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="notebook_with_long_markdown",
            prompt=(
                "Create a PostHog notebook titled 'Q4 funnel investigation'. "
                "The body must contain the following markdown verbatim — preserve every "
                "line, code fence, and quote exactly:\n\n"
                f"{NOTEBOOK_BODY}"
            ),
            expected={"target_tool": NOTEBOOK_TOOL},
        ),
        SandboxedEvalCase(
            name="skill_with_long_markdown",
            prompt=(
                "Create a new agent skill named 'triage-funnel-drop' in this PostHog "
                "project. Use the markdown below as the SKILL.md body, verbatim — "
                "preserve every line, code fence, and quote:\n\n"
                f"{SKILL_BODY}"
            ),
            expected={"target_tool": SKILL_TOOL},
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-cli-mcp-input-structured-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            CalledTargetTool(),
            PreferredExecForm(prefer="structured"),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )


@pytest.mark.django_db
async def eval_input_either(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    """Short payloads — inline JSON and structured ``input`` both acceptable."""
    if mcp_mode == "tools":
        pytest.skip("posthog:exec input field only exists in cli mode")

    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="dashboard_create_short",
            prompt=(
                "Create a PostHog dashboard named 'Onboarding signals' with description "
                "'Top-of-funnel checks for the onboarding flow.'"
            ),
            expected={"target_tool": DASHBOARD_TOOL},
        ),
        SandboxedEvalCase(
            name="insight_create_short",
            prompt=(
                "Create a PostHog trends insight named 'Daily pageviews' that counts "
                "the $pageview event over the last 7 days."
            ),
            expected={"target_tool": INSIGHT_TOOL},
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-cli-mcp-input-either-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            CalledTargetTool(),
            PreferredExecForm(prefer="either"),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
