"""Insight-retrieval eval cases for the sandboxed product-analytics agent.

Each case seeds 1000 noise insights plus a few distinctive lookup insights
into the per-case team via ``setup=seed_insight_noise``, then asks the
agent to find one specific insight and return its ID.

Two metrics:

* ``skill_loaded`` — did the agent load ``querying-posthog-data`` before
  reasoning about how to find the entity? Buying noise without skill
  guidance pushes the agent toward the wrong tool.
* ``lookup_id_in_output`` — does the agent's final message include the
  seeded insight's ID? Proves it actually queried PostHog rather than
  hallucinating a plausible-looking ID.

To run:
    pytest ee/hogai/eval/sandboxed/retrieval/eval_insight_retrieval.py
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.retrieval.scorers import LookupIdInOutput, SkillLoaded
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero
from ee.hogai.eval.sandboxed.seeders.insight import seed_insight_noise

SKILL_NAME = "querying-posthog-data"


@pytest.mark.django_db
async def eval_insight_retrieval(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="retrieval_insight_northern_lights",
            prompt=(
                "Find the saved insight named '[lookup] Northern Lights Funnel' "
                "in this PostHog project and return its numeric ID. Reply with just the ID."
            ),
            setup=seed_insight_noise,
        ),
        SandboxedEvalCase(
            name="retrieval_insight_aurora",
            prompt=(
                "Find the saved insight named '[lookup] Aurora Retention Cohort' "
                "in this PostHog project and return its numeric ID. Reply with just the ID."
            ),
            setup=seed_insight_noise,
        ),
        SandboxedEvalCase(
            name="retrieval_insight_solstice",
            prompt=(
                "Find the saved insight named '[lookup] Solstice Pageview Trend' "
                "in this PostHog project and return its numeric ID. Reply with just the ID."
            ),
            setup=seed_insight_noise,
        ),
        # Real-world fuzzy retrieval: user describes the insight in natural
        # language ("MAUs using the app") instead of naming it verbatim. From a
        # team-product-analytics report on a session that took ~50 tool calls
        # and ~15 minutes to return the wrong answer.
        SandboxedEvalCase(
            name="retrieval_insight_fuzzy_mau",
            prompt=(
                "find me a graph of MAUs using the app. "
                "it's probably an existing insight, and created/last used by "
                "me around this time last year."
            ),
            expected={"lookup_id_in_output": {"lookup_name": "Monthly Active Users (Hedgebox)"}},
            setup=seed_insight_noise,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-retrieval-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            SkillLoaded(skill_name=SKILL_NAME),
            LookupIdInOutput(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
