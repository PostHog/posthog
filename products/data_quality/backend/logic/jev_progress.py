from typing import TYPE_CHECKING

from django.db.models import Count, Q, Sum

from ..facade.contracts import QuestionProgress
from ..facade.enums import SubjectType
from ..models.question_execution import DataQualityQuestionExecution
from .jev_manifest import authorize_warehouse_question_subject
from .jev_question import QuestionConfig
from .subject_access import ReadableSubjects
from .subjects import resolve_subject

if TYPE_CHECKING:
    from posthog.models import Team, User


def question_progress(
    team: "Team", user: "User", suite_run_id: str, readable: ReadableSubjects | None = None
) -> list[QuestionProgress]:
    """Checkpoint progress of the suite's active question executions.

    ``readable`` is the caller's scope-restricted subject set; an API token whose scopes exclude a
    subject must not learn its check ids or row counts through the user's own grants.
    """
    executions = (
        DataQualityQuestionExecution.objects.for_team(team.id)
        .filter(suite_run_id=suite_run_id, finished_at__isnull=True)
        .annotate(
            completed_chunks=Count(
                "dataqualityquestioncheckpoint", filter=Q(dataqualityquestioncheckpoint__team_id=team.id)
            ),
            evaluated_rows=Sum(
                "dataqualityquestioncheckpoint__examined_row_count",
                filter=Q(dataqualityquestioncheckpoint__team_id=team.id),
            ),
        )
        .values(
            "definition_id",
            "subject_uuid",
            "check_config",
            "column_name",
            "manifest_key",
            "examined_row_count",
            "total_chunk_count",
            "completed_chunks",
            "evaluated_rows",
        )
    )
    progress: list[QuestionProgress] = []
    for execution in executions:
        if readable is not None and not readable.contains(SubjectType.TABLE, execution["subject_uuid"]):
            continue
        try:
            subject = resolve_subject(team.id, SubjectType.TABLE, str(execution["subject_uuid"]))
            config = QuestionConfig.model_validate(execution["check_config"])
            authorize_warehouse_question_subject(team, user, subject, config, execution["column_name"])
        except Exception:
            # Progress is also a row-count oracle; withhold it if current source access is unavailable.
            continue
        progress.append(
            QuestionProgress(
                check_id=str(execution["definition_id"]),
                preparing=not bool(execution["manifest_key"]),
                total_row_count=execution["examined_row_count"],
                evaluated_row_count=execution["evaluated_rows"] or 0,
                completed_chunk_count=execution["completed_chunks"],
                total_chunk_count=execution["total_chunk_count"],
            )
        )
    return progress
