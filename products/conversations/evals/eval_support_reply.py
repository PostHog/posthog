"""One-shot eval of the grounded support-reply pipeline.

Invented tickets (example.com, fake ids) plus a seeded business-knowledge corpus.
Mocked by default (sandbox draft stubbed). Set SUPPORT_REPLY_EVAL_LIVE=1 to run
the real draft agent.

Public rather than private: the suite compares a baseline against a later prompt
or model change, and that history lives in Braintrust. Every ticket and corpus
document is invented, so there is no customer text to keep off the wire.

To run:
    hogli evals eval_support_reply
    hogli evals eval_support_reply --eval how_to_sdk_install
    SUPPORT_REPLY_EVAL_LIVE=1 hogli evals eval_support_reply --eval how_to_sdk_install
"""

from __future__ import annotations

import asyncio

from products.conversations.evals.constants import LIVE_EVAL_ENV_VAR
from products.conversations.evals.fixtures import FIXTURES, FIXTURES_BY_NAME, expected_for
from products.conversations.evals.runner import live_eval_enabled, run_fixture
from products.conversations.evals.scorers import ALL_SCORERS
from products.conversations.evals.seeders import provision_eval_team, seed_case, teardown_eval_team
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval

SUITE_KIND = SuiteKind.ONE_SHOT

CASES = [
    BaseEvalCase(
        name=fixture.name,
        prompt=fixture.prompt,
        expected=expected_for(fixture),
        metadata={
            "ticket_type": fixture.ticket_type,
            "blocker": fixture.blocker,
            "expected_outcome": fixture.expected_outcome,
            "docs_source": fixture.docs_source,
            "live_env_var": LIVE_EVAL_ENV_VAR,
        },
    )
    for fixture in FIXTURES
]


async def eval_support_reply(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        fixture = FIXTURES_BY_NAME[case.name]
        live = live_eval_enabled()
        eval_team = await asyncio.to_thread(lambda: provision_eval_team(label=fixture.name))
        try:
            seed = await asyncio.to_thread(lambda: seed_case(eval_team=eval_team, fixture=fixture))
            return await run_fixture(fixture, seed, live=live)
        finally:
            await asyncio.to_thread(lambda: teardown_eval_team(eval_team=eval_team))

    await OneShotPublicEval(
        experiment_name="support-reply-pipeline",
        cases=CASES,
        scorers=list(ALL_SCORERS),
        task=task,
        ctx=ctx,
    )
