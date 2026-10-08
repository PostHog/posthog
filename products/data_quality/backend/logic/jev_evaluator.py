import math
from typing import TYPE_CHECKING, cast

from posthog.hogql import ast
from posthog.hogql.functions.prompt_jev import PromptJevCall
from posthog.hogql.transforms.prompt_jev import PromptJevRunner, validate_prompt_jev_access

from posthog.llm.system_one import NoulQuestion
from posthog.llm.system_one_client import GatewaySystemOneClient, build_system_one_client

from .jev_question import PartialQuestionDecisionsError

if TYPE_CHECKING:
    from posthog.models.team import Team


class QuestionGatewayEvaluator:
    def __init__(
        self,
        *,
        team: "Team",
        model_id: str,
        question: str,
        check_id: str,
        run_id: str,
        distinct_id: str | None,
    ) -> None:
        validate_prompt_jev_access(team)
        self.team = team
        self.distinct_id = distinct_id
        self.spec = PromptJevCall(
            input=ast.Constant(value=None),
            question=NoulQuestion(instructions=question),
            batch_size=16,
            model="jeeves",
        )
        client = build_system_one_client(
            model=model_id,
            ai_product="hogql_decide",
            team_id=team.pk,
            distinct_id=distinct_id,
            trace_id=run_id,
            properties={"data_quality_check_id": check_id, "data_quality_run_id": run_id},
        )
        if not isinstance(client, GatewaySystemOneClient):
            raise ValueError("Question checks require the billed AI gateway.")
        self.client = client

    def __call__(self, inputs: list[str]) -> list[float]:
        # Each manifest chunk gets Jev's existing byte, concurrency, row-isolation and time budgets.
        runner = PromptJevRunner(team_id=self.team.pk, distinct_id=self.distinct_id)
        runner.clients[self.spec.model] = self.client
        completed: dict[str, float] = {}

        def retain_batch(batch: dict[str, object]) -> None:
            for text, probability in batch.items():
                if type(probability) not in (int, float):
                    raise ValueError("Jev returned an invalid probability.")
                value = float(cast(float, probability))
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("Jev returned an invalid probability.")
                completed[text] = value

        try:
            decisions = runner.evaluate(self.spec, list(inputs), on_batch=retain_batch)
        except Exception:
            raise PartialQuestionDecisionsError(completed) from None
        if any(type(decision) not in (int, float) for decision in decisions):
            raise ValueError("Jev returned an invalid probability.")
        return [float(cast(float, decision)) for decision in decisions]
