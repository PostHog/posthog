"""Eval cases for the ``insight-create`` / ``insight-update`` MCP workflow.

The ``insight-create`` and ``insight-update`` tool descriptions instruct the
agent to validate the ``query`` payload through one of the ``query-*`` MCP
tools (``query-trends`` / ``query-funnel`` / ``query-retention`` /
``query-paths`` / ``query-stickiness`` / ``query-lifecycle``) BEFORE saving.
This eval grades that workflow:

* the matching ``query-*`` tool was run successfully at least once, and
* every successful ``insight-create`` / ``insight-update`` call was
  preceded by such a ``query-*`` call in the same run.

Correctness of the saved query shape is not scored here — the trends /
funnel / retention evals already cover that. This eval grades workflow
hygiene specific to the save tools.

To run:
    pytest ee/hogai/eval/sandboxed/product_analytics/eval_insight_save.py
"""

from __future__ import annotations

import logging
from typing import Any

from posthog.models.insight import Insight

from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.cli_mcp.scorers import CalledTargetTool
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.product_analytics.scorers import QueryBeforeInsightSave
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, RequiredToolCall

logger = logging.getLogger(__name__)


def _seed_funnel_insight(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Create a person-aggregated funnel insight the agent will be asked to update.

    Mirrors the Slack thread: a funnel saved as "Pageview → Signup funnel"
    that aggregates by person, which the agent should switch to aggregate by
    organization. Returns the seeded insight's metadata so the prompt and
    scorer can reference it.
    """
    insight = Insight.objects.create(
        team_id=context.team_id,
        created_by_id=context.user_id,
        name="Pageview to signup funnel",
        description="",
        saved=True,
        query={
            "kind": "InsightVizNode",
            "source": {
                "kind": "FunnelsQuery",
                "series": [
                    {"event": "$pageview", "kind": "EventsNode"},
                    {"event": "signed_up", "kind": "EventsNode"},
                ],
                "dateRange": {"date_from": "-30d"},
                "filterTestAccounts": True,
            },
        },
    )
    return {
        "seeded_insight": {
            "id": insight.id,
            "short_id": insight.short_id,
            "name": insight.name,
        }
    }


async def eval_insight_save(sandboxed_demo_data, pytestconfig, posthog_client):
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="create_trends_pageview",
            prompt=(
                "Save a new insight named 'Daily pageviews' that shows the daily $pageview trend "
                "over the last 30 days."
            ),
            expected={
                "called_target_tool": {"tool": "insight-create"},
            },
        ),
        SandboxedEvalCase(
            name="create_funnel_pageview_to_signup",
            prompt=(
                "Create and save an insight named 'Signup funnel' that tracks the conversion from "
                "$pageview to signed_up over the last 30 days."
            ),
            expected={
                "called_target_tool": {"tool": "insight-create"},
            },
        ),
        SandboxedEvalCase(
            name="update_funnel_aggregation_by_organization",
            # Mirrors the original Slack thread: the user wants to flip a
            # person-aggregated funnel to aggregate by organization, which
            # the agent often did by hand-editing JSON instead of going
            # through query-funnel first.
            prompt=(
                "Update the saved 'Pageview to signup funnel' insight so it aggregates by "
                "organization instead of by person."
            ),
            setup=_seed_funnel_insight,
            expected={
                "called_target_tool": {"tool": "insight-update"},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-insight-save",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            CalledTargetTool(),
            RequiredToolCall(required={"read-data-schema"}, name="verified_event_exists"),
            QueryBeforeInsightSave(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
