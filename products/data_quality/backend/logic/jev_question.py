import json
import time
from collections.abc import Callable, Sequence
from dataclasses import field
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.llm.system_one import NoulQuestion

from .contracts import SubjectRef
from .jev_cache import DecisionRequest, JevDecisionCache
from .spec import CheckConfig
from .types.common import column, subject_source


class QuestionConfig(CheckConfig):
    input_mode: Literal["column", "row"] = "column"
    question: str = Field(
        min_length=1, description="Yes/no question describing valid data. Yes is the expected answer."
    )
    columns: list[str] = Field(default_factory=list, description="Fields evaluated together in row mode.")
    min_probability: float = Field(default=0.8, ge=0, le=1, allow_inf_nan=False)
    max_failure_rate: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value: str) -> str:
        if not value.strip() or len(value.encode()) > 8192:
            raise ValueError("The question must be non-empty and at most 8 KiB.")
        return value

    @model_validator(mode="after")
    def selected_columns(self) -> Self:
        if self.input_mode == "column" and self.columns:
            raise ValueError("Column mode uses column_name, not columns.")
        if self.input_mode == "row" and (
            not self.columns
            or any(not name.strip() for name in self.columns)
            or len(set(self.columns)) != len(self.columns)
        ):
            raise ValueError("Row mode needs a non-empty list of distinct columns.")
        self.columns = sorted(self.columns)
        return self

    def input_columns(self, column_name: str) -> list[str]:
        if self.input_mode == "column":
            if not column_name:
                raise ValueError("Column mode needs column_name.")
            return [column_name]
        if column_name:
            raise ValueError("Row mode takes no column_name.")
        return self.columns

    def question_schema(self) -> str:
        return json.dumps(NoulQuestion(instructions=self.question).to_json(), sort_keys=True, separators=(",", ":"))


def question_input_query(subject: SubjectRef, config: QuestionConfig, column_name: str) -> ast.SelectQuery:
    """One exhaustive projection, grouped by the exact evaluator input with source multiplicities."""
    names = config.input_columns(column_name)
    if config.input_mode == "column":
        input_expression: ast.Expr = ast.Call(name="toString", args=[column(names[0])])
    else:
        # Serializing each field first lets mixed column types share an Array(String), while the
        # final JSON preserves native values and nulls rather than coercing every field to text.
        fields: list[ast.Expr] = [
            ast.Call(
                name="toJSONString",
                args=[
                    ast.Tuple(
                        exprs=[ast.Constant(value=name), ast.Call(name="toTypeName", args=[column(name)]), column(name)]
                    )
                ],
            )
            for name in names
        ]
        input_expression = ast.Call(
            name="concat",
            args=[
                ast.Constant(value="["),
                ast.Call(name="arrayStringConcat", args=[ast.Array(exprs=fields), ast.Constant(value=",")]),
                ast.Constant(value="]"),
            ],
        )
    input_rows = ast.SelectQuery(
        select=[ast.Alias(alias="input", expr=input_expression)],
        select_from=subject_source(subject),
    )
    return ast.SelectQuery(
        select=[ast.Field(chain=["input"]), ast.Alias(alias="row_count", expr=ast.Call(name="count", args=[]))],
        select_from=ast.JoinExpr(table=input_rows),
        group_by=[ast.Field(chain=["input"])],
    )


@frozen
class WeightedInput:
    text: str | None = field(repr=False)
    row_count: int

    def __post_init__(self) -> None:
        if type(self.row_count) is not int or self.row_count < 1:
            raise ValueError("An input must represent at least one row.")
        if self.text is not None and not isinstance(self.text, str):
            raise ValueError("A question input must be text or null.")


@frozen
class QuestionChunkResult:
    examined_row_count: int
    failed_row_count: int
    unique_input_count: int
    reused_decision_count: int
    new_decision_count: int

    def __post_init__(self) -> None:
        counts = (
            self.examined_row_count,
            self.failed_row_count,
            self.unique_input_count,
            self.reused_decision_count,
            self.new_decision_count,
        )
        if (
            any(type(count) is not int or count < 0 for count in counts)
            or self.failed_row_count > self.examined_row_count
            or self.reused_decision_count + self.new_decision_count != self.unique_input_count
        ):
            raise ValueError("Question chunk counts are inconsistent.")


class PartialQuestionDecisionsError(RuntimeError):
    def __init__(self, decisions: dict[str, float]) -> None:
        super().__init__("Question execution failed with incomplete coverage.")
        self.decisions = decisions


class QuestionChunkEvaluator:
    def __init__(
        self,
        *,
        cache: JevDecisionCache,
        config: QuestionConfig,
        model_id: str,
        model_revision: str,
        evaluate: Callable[[list[str]], list[float]],
        max_input_bytes: int = 8192,
        max_chunk_inputs: int = 256,
        wait_seconds: float = 180,
        max_inference_inputs: int = 10_000,
        max_run_seconds: float = 900,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            not model_id.strip()
            or not model_revision.strip()
            or max_input_bytes < 1
            or max_chunk_inputs < 1
            or wait_seconds <= 0
            or max_inference_inputs < 0
            or max_run_seconds <= 0
        ):
            raise ValueError("Invalid question evaluator configuration.")
        self.cache = cache
        self.config = config.model_copy(deep=True)
        self.model_id = model_id
        self.model_revision = model_revision
        self.evaluate = evaluate
        self.max_input_bytes = max_input_bytes
        self.max_chunk_inputs = max_chunk_inputs
        self.wait_seconds = wait_seconds
        self.clock = clock
        self.wait = wait
        self.max_inference_inputs = max_inference_inputs
        self.inference_inputs = 0
        self.run_deadline = clock() + max_run_seconds

    def check_deadline(self) -> None:
        """Every path that can advance coverage checks this, including ones that never call inference."""
        if self.clock() >= self.run_deadline:
            raise RuntimeError("Question evaluation timed out with incomplete coverage.")

    def run(self, inputs: Sequence[WeightedInput]) -> QuestionChunkResult:
        self.check_deadline()
        if len(inputs) > self.max_chunk_inputs:
            raise ValueError("Question manifest chunk exceeds its input limit.")
        requests: dict[str, DecisionRequest] = {}
        weights: dict[str, int] = {}
        null_rows = 0
        for item in inputs:
            if item.text is None:
                if self.config.input_mode != "column":
                    raise ValueError("Row inputs must retain labeled null fields.")
                null_rows += item.row_count
                continue
            if len(item.text.encode()) > self.max_input_bytes:
                raise ValueError("A question input exceeds 8 KiB; no input was truncated.")
            request = DecisionRequest(
                input=item.text,
                question_schema=self.config.question_schema(),
                model_id=self.model_id,
                model_revision=self.model_revision,
            )
            key = request.key(self.cache.team_id)
            requests[key] = request
            weights[key] = weights.get(key, 0) + item.row_count
        decisions = self.cache.read(list(requests.values()))
        new: set[str] = set()
        deadline = min(self.clock() + self.wait_seconds, self.run_deadline)
        while missing := {key: request for key, request in requests.items() if key not in decisions}:
            if self.clock() >= deadline:
                raise RuntimeError("Question evaluation timed out with incomplete coverage.")
            leases = self.cache.acquire(list(missing.values()))
            try:
                # A winner can publish between our first read and SET NX. Recheck before spending credits.
                decisions.update(self.cache.read(list(missing.values())))
                owned = [key for key in leases if key not in decisions]
                if owned:
                    if self.inference_inputs + len(owned) > self.max_inference_inputs:
                        raise RuntimeError(
                            "Question evaluation exhausted its inference budget with incomplete coverage."
                        )
                    self.inference_inputs += len(owned)
                    with self.cache.maintain([leases[key] for key in owned]):
                        try:
                            probabilities = self.evaluate([requests[key].input for key in owned])
                        except PartialQuestionDecisionsError as error:
                            self.cache.publish(
                                [
                                    (leases[key], requests[key], error.decisions[requests[key].input])
                                    for key in owned
                                    if requests[key].input in error.decisions
                                ]
                            )
                            raise
                    if len(probabilities) != len(owned):
                        raise ValueError("Jev returned an incomplete decision batch.")
                    if self.clock() >= deadline:
                        raise RuntimeError("Question evaluation timed out with incomplete coverage.")
                    published = self.cache.publish(
                        [
                            (leases[key], requests[key], probability)
                            for key, probability in zip(owned, probabilities, strict=True)
                        ]
                    )
                    new.update(published)
                    decisions.update(
                        {
                            key: probability
                            for key, probability in zip(owned, probabilities, strict=True)
                            if key in published
                        }
                    )
                decisions.update(self.cache.read(list(missing.values())))
            finally:
                self.cache.release(list(leases.values()))
            if len(decisions) != len(requests):
                self.wait(min(0.25, max(0, deadline - self.clock())))
        self.check_deadline()
        return QuestionChunkResult(
            examined_row_count=null_rows + sum(weights.values()),
            failed_row_count=null_rows
            + sum(count for key, count in weights.items() if decisions[key] < self.config.min_probability),
            unique_input_count=len(requests),
            reused_decision_count=len(requests) - len(new),
            new_decision_count=len(new),
        )
