import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q

from asgiref.sync import async_to_sync

from posthog.hogql.transforms.prompt_jev import validate_prompt_jev_access

from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.user import User
from posthog.redis import get_client
from posthog.storage import object_storage

from ..facade.enums import CheckRunStatus, CheckSeverity, CheckType, SubjectType, SuiteRunTrigger
from ..models import (
    DataQualityCheck,
    DataQualityQuestionCheckpoint,
    DataQualityQuestionExecution,
    DataQualityQuestionSnapshot,
    DataQualitySuiteRun,
)
from .contracts import PreparedQuestion
from .jev_cache import EVALUATOR_VERSION, JevDecisionCache
from .jev_evaluator import QuestionGatewayEvaluator
from .jev_manifest import (
    CHUNK_INPUTS,
    MAX_FROZEN_INPUTS,
    QuestionManifest,
    QuestionManifestStore,
    QuestionResult,
    authorize_warehouse_question_subject,
    freeze_question_inputs,
    warehouse_question_inputs,
)
from .jev_question import QuestionChunkEvaluator, QuestionChunkResult, QuestionConfig
from .run_records import record_check_run
from .runner import CheckOutcome, _update_check
from .subjects import resolve_subject

if TYPE_CHECKING:
    from .contracts import SubjectRef

MAX_INFERENCE_INPUTS = 10_000
RUN_SECONDS = 900
INCOMPLETE_ERROR = "Question execution failed with incomplete coverage."


class DurableQuestionRunner:
    def __init__(self, team_id: int, execution_id: str) -> None:
        self.execution = (
            DataQualityQuestionExecution.objects.for_team(team_id).select_related("principal").get(id=execution_id)
        )
        self.team = Team.objects.get(id=team_id)
        self.config = QuestionConfig.model_validate(self.execution.check_config)
        self.store = QuestionManifestStore()

    @classmethod
    def start(cls, team_id: int, suite_id: str, check_id: str) -> "DurableQuestionRunner":
        existing = (
            DataQualityQuestionExecution.objects.for_team(team_id)
            .filter(suite_run_id=suite_id, definition_id=check_id)
            .first()
        )
        if existing is not None:
            return cls(team_id, str(existing.id))
        suite = DataQualitySuiteRun.objects.for_team(team_id).get(id=suite_id)
        check = DataQualityCheck.objects.for_team(team_id).get(id=check_id, check_type=CheckType.QUESTION)
        if (
            check.subject_type != SubjectType.TABLE
            or check.subject_uuid is None
            or check.severity != CheckSeverity.WARN
        ):
            raise ValueError(INCOMPLETE_ERROR)
        principal = (
            suite.created_by if suite.trigger == SuiteRunTrigger.MANUAL else check.definition_author or check.created_by
        )
        execution, _ = DataQualityQuestionExecution.objects.for_team(team_id).get_or_create(
            suite_run=suite,
            definition_id=check.id,
            defaults={
                "team_id": team_id,
                "quality_check": check,
                "principal": principal,
                "subject_uuid": check.subject_uuid,
                "subject_name": check.subject_name,
                "column_name": check.column_name,
                "check_config": check.config,
                "check_fingerprint": check.fingerprint,
                "model_id": settings.HOGQL_PROMPT_JEV_MODEL,
                "model_revision": settings.DATA_QUALITY_JEV_MODEL_REVISION,
                "evaluator_version": EVALUATOR_VERSION,
                "deadline": datetime.now(UTC) + timedelta(seconds=RUN_SECONDS),
            },
        )
        return cls(team_id, str(execution.id))

    def authorize(self, *, completed: bool = False) -> "SubjectRef":
        execution = self.execution
        if execution.principal is None or (
            not completed
            and (
                not execution.model_revision.strip()
                or execution.model_revision != settings.DATA_QUALITY_JEV_MODEL_REVISION
                or execution.evaluator_version != EVALUATOR_VERSION
                or datetime.now(UTC) >= execution.deadline
            )
        ):
            raise ValueError(INCOMPLETE_ERROR)
        principal = User.objects.get(id=execution.principal_id, is_active=True)
        if not principal.teams.filter(id=self.team.id).exists():
            raise ValueError(INCOMPLETE_ERROR)
        self.execution.principal = principal
        subject = resolve_subject(self.team.id, SubjectType.TABLE, str(execution.subject_uuid))
        authorize_warehouse_question_subject(
            self.team, execution.principal, subject, self.config, execution.column_name
        )
        if not completed:
            validate_prompt_jev_access(self.team)
        return subject

    def register_attempt(self, prefix: str) -> None:
        DataQualityQuestionSnapshot.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            execution=self.execution,
            prefix=prefix,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )

    def prepare(self) -> PreparedQuestion:
        if self.execution.finished_at is not None:
            return PreparedQuestion(execution_id=str(self.execution.id), chunk_count=0)
        subject = self.authorize()
        principal = self.execution.principal
        if principal is None:
            raise ValueError(INCOMPLETE_ERROR)
        if not self.execution.manifest_key:
            manifest = async_to_sync(freeze_question_inputs)(
                inputs=warehouse_question_inputs(
                    team=self.team,
                    user=principal,
                    subject=subject,
                    config=self.config,
                    column_name=self.execution.column_name,
                ),
                store=self.store,
                team_id=self.team.id,
                run_id=str(self.execution.id),
                subject_uuid=str(self.execution.subject_uuid),
                model_id=self.execution.model_id,
                model_revision=self.execution.model_revision,
                config=self.config,
                column_name=self.execution.column_name,
                register_attempt=self.register_attempt,
            )
            key = f"{manifest.prefix}/manifest.json"
            with transaction.atomic():
                selected = (
                    DataQualityQuestionExecution.objects.for_team(self.team.id)
                    .select_for_update()
                    .get(id=self.execution.id)
                )
                if not selected.manifest_key and selected.finished_at is None:
                    selected.manifest_key = key
                    selected.total_chunk_count = manifest.chunk_count
                    selected.examined_row_count = manifest.examined_row_count
                    selected.unique_input_count = manifest.unique_input_count
                    selected.save(
                        update_fields=["manifest_key", "total_chunk_count", "examined_row_count", "unique_input_count"]
                    )
                self.execution = selected
            if self.execution.manifest_key != key:
                self.store.delete(manifest)
        manifest = self.manifest()
        return PreparedQuestion(execution_id=str(self.execution.id), chunk_count=manifest.chunk_count)

    def manifest(self) -> QuestionManifest:
        manifest = self.store.read_manifest(
            self.execution.manifest_key, team_id=self.team.id, run_id=str(self.execution.id)
        )
        if (
            manifest.subject_uuid != str(self.execution.subject_uuid)
            or manifest.column_name != self.execution.column_name
            or manifest.question_config != self.config
            or manifest.model_id != self.execution.model_id
            or manifest.model_revision != self.execution.model_revision
            or manifest.evaluator_version != self.execution.evaluator_version
            or manifest.chunk_count != self.execution.total_chunk_count
            or manifest.examined_row_count != self.execution.examined_row_count
            or manifest.unique_input_count != self.execution.unique_input_count
        ):
            raise ValueError(INCOMPLETE_ERROR)
        return manifest

    def reserve(self, count: int) -> None:
        if count < 1:
            raise ValueError(INCOMPLETE_ERROR)
        updated = (
            DataQualityQuestionExecution.objects.for_team(self.team.id)
            .filter(
                id=self.execution.id,
                finished_at__isnull=True,
                deadline__gt=datetime.now(UTC),
                reserved_inference_inputs__lte=MAX_INFERENCE_INPUTS - count,
            )
            .update(reserved_inference_inputs=F("reserved_inference_inputs") + count)
        )
        if updated != 1:
            raise ValueError(INCOMPLETE_ERROR)

    def chunk(self, index: int) -> None:
        self.authorize()
        manifest = self.manifest()
        if not 0 <= index < manifest.chunk_count or self.execution.finished_at is not None:
            raise ValueError(INCOMPLETE_ERROR)
        checkpoints = DataQualityQuestionCheckpoint.objects.for_team(self.team.id)
        if checkpoints.filter(execution=self.execution, chunk_index=index).exists():
            return

        def evaluate(inputs: list[str]) -> list[float]:
            self.authorize()
            principal = self.execution.principal
            if principal is None:
                raise ValueError(INCOMPLETE_ERROR)
            gateway = QuestionGatewayEvaluator(
                team=self.team,
                model_id=self.execution.model_id,
                question=self.config.question,
                check_id=str(self.execution.definition_id),
                run_id=str(self.execution.id),
                distinct_id=principal.distinct_id,
            )
            self.reserve(len(inputs))
            return gateway(inputs)

        evaluator = QuestionChunkEvaluator(
            cache=JevDecisionCache(get_client(socket_timeout=5, socket_connect_timeout=5), team_id=self.team.id),
            config=self.config,
            model_id=self.execution.model_id,
            model_revision=self.execution.model_revision,
            evaluate=evaluate,
            max_run_seconds=max(0.001, (self.execution.deadline - datetime.now(UTC)).total_seconds()),
        )
        result = evaluator.run(self.store.read_chunk(manifest, index))
        self.authorize()
        # The run lock serializes checkpoint commits with finalization, never with inference.
        with transaction.atomic():
            active = (
                DataQualityQuestionExecution.objects.for_team(self.team.id)
                .select_for_update()
                .get(id=self.execution.id)
            )
            if active.finished_at is not None:
                raise ValueError(INCOMPLETE_ERROR)
            checkpoints.get_or_create(
                execution=active, chunk_index=index, defaults={"team_id": self.team.id, **asdict(result)}
            )

    def finish(self, *, errored: bool = False) -> QuestionResult:
        self.execution.refresh_from_db()
        authorized = True
        try:
            self.authorize(completed=self.execution.finished_at is not None)
        except Exception:
            authorized = False
            errored = True
        with transaction.atomic():
            execution = (
                DataQualityQuestionExecution.objects.for_team(self.team.id)
                .select_for_update()
                .get(id=self.execution.id)
            )
            if execution.finished_at is not None:
                result = QuestionResult.model_validate_json(json.dumps(execution.result))
                if not authorized:
                    return result.model_copy(
                        update={
                            "status": CheckRunStatus.ERRORED,
                            "coverage_complete": False,
                            "failure_rate": None,
                            "examined_row_count": 0,
                            "failed_row_count": 0,
                            "unique_input_count": 0,
                            "reused_decision_count": 0,
                            "new_decision_count": 0,
                            "completed_chunk_count": 0,
                            "total_chunk_count": 0,
                        }
                    )
                return result
            checkpoints = list(
                DataQualityQuestionCheckpoint.objects.for_team(self.team.id)
                .filter(execution=execution)
                .order_by("chunk_index")
            )
            coverage = QuestionChunkResult(
                examined_row_count=sum(row.examined_row_count for row in checkpoints),
                failed_row_count=sum(row.failed_row_count for row in checkpoints),
                unique_input_count=sum(row.unique_input_count for row in checkpoints),
                reused_decision_count=sum(row.reused_decision_count for row in checkpoints),
                new_decision_count=sum(row.new_decision_count for row in checkpoints),
            )
            counts = asdict(coverage)
            complete = (
                not errored
                and bool(execution.manifest_key)
                and [row.chunk_index for row in checkpoints] == list(range(execution.total_chunk_count))
                and counts["examined_row_count"] == execution.examined_row_count
                and counts["unique_input_count"] == execution.unique_input_count
            )
            rate = (
                counts["failed_row_count"] / counts["examined_row_count"]
                if complete and counts["examined_row_count"]
                else None
            )
            status = (
                CheckRunStatus.ERRORED
                if not complete
                else (
                    CheckRunStatus.SKIPPED
                    if rate is None
                    else CheckRunStatus.PASSED
                    if rate <= self.config.max_failure_rate
                    else CheckRunStatus.FAILED
                )
            )
            # Authorization failures must not expose previously accumulated counts through the run history.
            result_counts = counts if authorized else dict.fromkeys(counts, 0)
            result = QuestionResult(
                status=status,
                **result_counts,
                failure_rate=rate if authorized else None,
                completed_chunk_count=len(checkpoints) if authorized else 0,
                total_chunk_count=execution.total_chunk_count if authorized else 0,
                coverage_complete=complete,
            )
            suite = DataQualitySuiteRun.objects.for_team(self.team.id).get(id=execution.suite_run_id)
            now = datetime.now(UTC)
            run = record_check_run(
                self.team.id,
                suite_run=suite,
                quality_check=execution.quality_check,
                subject_type=SubjectType.TABLE,
                subject_uuid=execution.subject_uuid,
                subject_name=execution.subject_name,
                check_type=CheckType.QUESTION,
                check_fingerprint=execution.check_fingerprint,
                column_name=execution.column_name,
                check_config=execution.check_config,
                check_severity=CheckSeverity.WARN,
                referenced_subjects=[],
                status=status,
                failed_row_count=result.failed_row_count if complete else None,
                observed_value=rate,
                error="" if complete else INCOMPLETE_ERROR,
                started_at=execution.created_at,
                finished_at=now,
                duration_ms=int((now - execution.created_at).total_seconds() * 1000),
            )
            execution.check_run = run
            execution.result = result.model_dump(mode="json")
            execution.finished_at = now
            execution.save(update_fields=["check_run", "result", "finished_at"])
            check = execution.quality_check
            if check is not None and check.fingerprint == execution.check_fingerprint:
                with team_scope(self.team.id):
                    _update_check(
                        check,
                        CheckOutcome(
                            status=status, error=run.error, failed_row_count=run.failed_row_count, observed_value=rate
                        ),
                        now,
                    )
        return result


def cleanup_question_snapshots(*, heartbeat: Callable[[], None] | None = None) -> int:
    now = datetime.now(UTC)
    snapshots = (
        DataQualityQuestionSnapshot.objects.unscoped()
        .filter(Q(expires_at__lte=now) | Q(execution__finished_at__lte=now - timedelta(minutes=5)))
        .order_by("expires_at")
    )
    cleaned = 0
    for snapshot in snapshots[:1000]:
        # Attempts are registered before any object write, so even a worker crash leaves a cleanup owner.
        for start in range(0, MAX_FROZEN_INPUTS, CHUNK_INPUTS * 128):
            keys = [
                f"{snapshot.prefix}/chunks/{index}.json"
                for index in range(
                    start // CHUNK_INPUTS,
                    min((start // CHUNK_INPUTS) + 128, (MAX_FROZEN_INPUTS + CHUNK_INPUTS - 1) // CHUNK_INPUTS),
                )
            ]
            failed = object_storage.delete_objects(keys)
            if failed:
                raise RuntimeError("Question snapshot cleanup was incomplete.")
            if heartbeat is not None:
                heartbeat()
        object_storage.delete(f"{snapshot.prefix}/manifest.json")
        snapshot.delete()
        cleaned += 1
    return cleaned
