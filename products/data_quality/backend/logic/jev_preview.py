from typing import TYPE_CHECKING
from uuid import uuid4

from django.conf import settings

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.transforms.prompt_jev import validate_prompt_jev_access

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import User
from posthog.redis import get_client

from ..facade.contracts import QuestionPreview, QuestionPreviewInput
from .contracts import SubjectRef
from .jev_cache import JevDecisionCache
from .jev_evaluator import QuestionGatewayEvaluator
from .jev_manifest import authorize_warehouse_question_subject
from .jev_question import (
    QUESTION_PREVIEW_ROW_LIMIT,
    QuestionChunkEvaluator,
    QuestionConfig,
    WeightedInput,
    question_preview_query,
)

if TYPE_CHECKING:
    from posthog.models.team import Team


class QuestionPreviewRunner:
    def __init__(
        self, *, team: "Team", user: User, subject: SubjectRef, config: QuestionConfig, column_name: str
    ) -> None:
        self.team = team
        self.user_id = user.id
        self.subject = subject
        self.config = config
        self.column_name = column_name
        self.model_revision = settings.DATA_QUALITY_JEV_MODEL_REVISION
        if not self.model_revision.strip():
            raise ValueError("Question checks require an immutable model revision.")
        self.run_id = str(uuid4())

    def authorize(self) -> User:
        principal = User.objects.get(id=self.user_id, is_active=True)
        if not principal.teams.filter(id=self.team.id).exists():
            raise ValueError("Question preview access is unavailable.")
        authorize_warehouse_question_subject(self.team, principal, self.subject, self.config, self.column_name)
        validate_prompt_jev_access(self.team)
        return principal

    def evaluate(self, inputs: list[str]) -> list[float]:
        principal = self.authorize()
        return QuestionGatewayEvaluator(
            team=self.team,
            model_id=settings.HOGQL_PROMPT_JEV_MODEL,
            question=self.config.question,
            check_id="preview",
            run_id=self.run_id,
            distinct_id=principal.distinct_id,
        )(inputs)

    def run(self) -> QuestionPreview:
        principal = self.authorize()
        database, modifiers = authorize_warehouse_question_subject(
            self.team, principal, self.subject, self.config, self.column_name
        )
        with tags_context(
            product=Product.DATA_QUALITY,
            feature=Feature.DATA_QUALITY_CHECK,
            data_quality_run_id=self.run_id,
            data_quality_check_type="question",
            data_quality_subject_type=self.subject.subject_type,
            data_quality_subject_id=self.subject.subject_uuid,
        ):
            response = execute_hogql_query(
                query=question_preview_query(self.subject, self.config, self.column_name),
                team=self.team,
                user=principal,
                query_type="data_quality_question_preview",
                context=HogQLContext(team_id=self.team.id, user=principal, database=database, modifiers=modifiers),
                modifiers=modifiers,
                settings=HogQLGlobalSettings(max_execution_time=15, timeout_overflow_mode="throw"),
            )
            if response.error or response.hasMore:
                raise ValueError("Question preview could not read its selected rows.")
            inputs = [WeightedInput(text=row[0], row_count=row[1]) for row in response.results or []]
            if sum(item.row_count for item in inputs) > QUESTION_PREVIEW_ROW_LIMIT:
                raise ValueError("Question preview exceeded its row limit.")
            self.authorize()
            probabilities: dict[str, float] = {}
            result = QuestionChunkEvaluator(
                cache=JevDecisionCache(get_client(socket_timeout=5, socket_connect_timeout=5), team_id=self.team.id),
                config=self.config,
                model_id=settings.HOGQL_PROMPT_JEV_MODEL,
                model_revision=self.model_revision,
                evaluate=self.evaluate,
                max_inference_inputs=QUESTION_PREVIEW_ROW_LIMIT,
                max_run_seconds=60,
                wait_seconds=60,
            ).run(inputs, on_decisions=probabilities.update)
            self.authorize()
            return QuestionPreview(
                inputs=[
                    QuestionPreviewInput(
                        input=item.text,
                        row_count=item.row_count,
                        probability=None if item.text is None else probabilities[item.text],
                    )
                    for item in inputs
                ],
                row_limit=QUESTION_PREVIEW_ROW_LIMIT,
                examined_row_count=result.examined_row_count,
                reused_decision_count=result.reused_decision_count,
                new_decision_count=result.new_decision_count,
            )
