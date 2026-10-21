from collections.abc import Callable
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.redis import get_client

from .contracts import SubjectRef
from .jev_cache import JevDecisionCache
from .jev_evaluator import QuestionGatewayEvaluator
from .jev_manifest import (
    QuestionManifest,
    QuestionManifestStore,
    QuestionResult,
    authorize_warehouse_question_subject,
    evaluate_question_manifest,
    freeze_question_inputs,
    warehouse_question_inputs,
)
from .jev_question import QuestionChunkEvaluator, QuestionChunkResult, QuestionConfig

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User


class WarehouseQuestionExecutor:
    def __init__(
        self,
        *,
        team: "Team",
        user: "User",
        subject: SubjectRef,
        config: QuestionConfig,
        column_name: str,
        model_id: str,
        model_revision: str,
        check_id: str,
        run_id: str,
        reserve_inference_inputs: Callable[[int], None],
    ) -> None:
        if not model_id.strip() or not model_revision.strip():
            raise ValueError("Question checks require an immutable model or deployment revision.")
        config.input_columns(column_name)
        self.team = team
        self.user = user
        self.subject = subject
        self.config = config.model_copy(deep=True)
        self.column_name = column_name
        self.model_id = model_id
        self.model_revision = model_revision
        self.check_id = check_id
        self.run_id = run_id
        self.reserve_inference_inputs = reserve_inference_inputs
        self.store = QuestionManifestStore()
        self.gateway: QuestionGatewayEvaluator | None = None

    def _authorize(self) -> None:
        authorize_warehouse_question_subject(self.team, self.user, self.subject, self.config, self.column_name)

    def _evaluate(self, inputs: list[str]) -> list[float]:
        # The reservation has no release callback, so it is spent only once inference can actually run.
        if self.gateway is None:
            self.gateway = QuestionGatewayEvaluator(
                team=self.team,
                model_id=self.model_id,
                question=self.config.question,
                check_id=self.check_id,
                run_id=self.run_id,
                distinct_id=self.user.distinct_id,
            )
        self.reserve_inference_inputs(len(inputs))
        return self.gateway(inputs)

    def _manifest(self, key: str | None, save_manifest: Callable[[str], str]) -> QuestionManifest:
        self._authorize()
        if key is not None:
            manifest = self.store.read_manifest(key, team_id=self.team.id, run_id=self.run_id)
        else:
            manifest = async_to_sync(freeze_question_inputs)(
                inputs=warehouse_question_inputs(
                    team=self.team,
                    user=self.user,
                    subject=self.subject,
                    config=self.config,
                    column_name=self.column_name,
                ),
                store=self.store,
                team_id=self.team.id,
                run_id=self.run_id,
                subject_uuid=self.subject.subject_uuid,
                model_id=self.model_id,
                model_revision=self.model_revision,
                config=self.config,
                column_name=self.column_name,
            )
            proposed_key = f"{manifest.prefix}/manifest.json"
            winning_key = save_manifest(proposed_key)
            if winning_key != proposed_key:
                self.store.delete(manifest)
                manifest = self.store.read_manifest(winning_key, team_id=self.team.id, run_id=self.run_id)
        if manifest.subject_uuid != self.subject.subject_uuid or manifest.column_name != self.column_name:
            raise ValueError("The question manifest does not match its subject or input selection.")
        return manifest

    def run(
        self,
        *,
        manifest_key: str | None,
        save_manifest: Callable[[str], str],
        load_checkpoint: Callable[[int], QuestionChunkResult | None],
        save_checkpoint: Callable[[int, QuestionChunkResult], QuestionChunkResult],
    ) -> QuestionResult:
        """Callbacks must atomically persist the first manifest and checkpoints for this run."""
        try:
            with tags_context(
                product=Product.DATA_QUALITY,
                feature=Feature.DATA_QUALITY_CHECK,
                data_quality_check_id=self.check_id,
                data_quality_run_id=self.run_id,
                data_quality_check_type="question",
                data_quality_subject_type=self.subject.subject_type,
                data_quality_subject_id=self.subject.subject_uuid,
            ):
                manifest = self._manifest(manifest_key, save_manifest)
                cache = JevDecisionCache(get_client(socket_timeout=5, socket_connect_timeout=5), team_id=self.team.id)
                evaluator = QuestionChunkEvaluator(
                    cache=cache,
                    config=self.config,
                    model_id=self.model_id,
                    model_revision=self.model_revision,
                    evaluate=self._evaluate,
                )
                return evaluate_question_manifest(
                    manifest=manifest,
                    store=self.store,
                    evaluator=evaluator,
                    authorize=self._authorize,
                    load_checkpoint=load_checkpoint,
                    save_checkpoint=save_checkpoint,
                )
        except Exception:
            # Database and decoder errors can contain source values, so callers receive no raw cause.
            raise RuntimeError("Question execution failed with incomplete coverage.") from None
