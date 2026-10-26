from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import yaml

from products.business_knowledge.backend.logic import create_text_source, search_knowledge
from products.business_knowledge.backend.models import KnowledgeDocument, SafetyVerdict
from products.business_knowledge.evals.offline_config import offline_suite
from products.conversations.evals.seeders import provision_eval_team, teardown_eval_team
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.harness.context import EvalContext

NO_SEND_LOGS = True

SUITE_KIND = SuiteKind.ONE_SHOT


class RetrievalQuery(TypedDict):
    query: str
    expect_found: bool


class RetrievalSource(TypedDict):
    source_name: str
    text: str
    queries: list[RetrievalQuery]


CORPUS: list[RetrievalSource] = yaml.safe_load(
    (Path(__file__).parents[1] / "backend/tests/fixtures/retrieval_eval.yaml").read_text()
)
CASES = [
    BaseEvalCase(
        name=f"{entry['source_name']}|{query['query']}",
        prompt=query["query"],
        expected={"retrieval_match": {"found": query["expect_found"]}},
        metadata={"source_name": entry["source_name"]},
    )
    for entry in CORPUS
    for query in entry["queries"]
]


class RetrievalMatch(Scorer):
    def _name(self) -> str:
        return "retrieval_match"

    def _run_eval_sync(
        self, output: dict[str, object] | None, expected: dict[str, object] | None = None, **kwargs: object
    ) -> Score:
        expectation = (expected or {}).get(self._name())
        if output is None or not isinstance(expectation, dict):
            return Score(name=self._name(), score=None, metadata={"reason": "Retrieval did not complete"})
        return Score(
            name=self._name(),
            score=float(output["found"] == expectation["found"]),
            metadata={"source_names": output["source_names"]},
        )


def search_case(case: BaseEvalCase) -> dict[str, object]:
    eval_team = provision_eval_team(label="knowledge-retrieval")
    try:
        for entry in CORPUS:
            create_text_source(
                team_id=eval_team.team.id,
                created_by_id=eval_team.user.id,
                name=entry["source_name"],
                text=entry["text"],
            )
        KnowledgeDocument.objects.for_team(eval_team.team.id).update(safety_verdict=SafetyVerdict.SAFE)
        results = search_knowledge(eval_team.team.id, case.prompt)
        return {"found": bool(results), "source_names": sorted({result.source_name for result in results})}
    finally:
        teardown_eval_team(eval_team=eval_team)


async def eval_retrieval(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, object]:
        return await asyncio.to_thread(search_case, case)

    await OneShotPrivateEval(
        no_send_logs=NO_SEND_LOGS,
        experiment_name="business-knowledge-retrieval",
        cases=CASES,
        task=task,
        scorers=[RetrievalMatch()],
        offline_suite=offline_suite(
            "business_knowledge/eval_retrieval::eval_retrieval", metrics=["retrieval_match"], suite_kind=SUITE_KIND
        ),
        send_to_posthog=True,
        ctx=ctx,
    )
