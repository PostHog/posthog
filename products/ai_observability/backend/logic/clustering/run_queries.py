from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ...facade.clustering_contracts import ClusteringJobProgress, ClusteringRunContext
from ...models.clustering_job import ClusteringJob
from ...models.clustering_run import ClusteringRun
from .constants import FIRST_RUN_SAMPLE_LIMIT, MIN_CLUSTERING_ITEMS, clustering_lookback_days
from .permissions import can_access_clustering_filters


def load_job_progress(team_id: int, user: User) -> list[ClusteringJobProgress]:
    runs = {
        str(run.job_id): run
        for run in ClusteringRun.objects.for_team(team_id).order_by("job_id", "-created_at").distinct("job_id")
    }
    progress = []
    for job in ClusteringJob.objects.filter(team_id=team_id, enabled=True).order_by("created_at"):
        run = runs.get(str(job.id))
        if not can_access_clustering_filters(team_id, user, run.event_filters if run else job.event_filters):
            continue
        progress.append(
            ClusteringJobProgress(
                job_id=str(job.id),
                name=job.name,
                analysis_level=job.analysis_level,
                has_filters=bool(job.event_filters),
                minimum=MIN_CLUSTERING_ITEMS,
                lookback_days=clustering_lookback_days(job.analysis_level),
                status=run.status if run else None,
                eligible_count=run.eligible_count if run else None,
                prepared_count=run.prepared_count if run else 0,
                cluster_count=run.cluster_count if run else None,
                failure_reason=run.failure_reason if run else "",
                updated_at=run.updated_at if run else None,
                result_run_id=run.result_run_id if run else "",
            )
        )
    return progress


def count_ready_items(team_id: int, context: ClusteringRunContext, start: datetime, end: datetime) -> int:
    document_type = {
        "trace": "llm-trace-summary-detailed",
        "generation": "llm-generation-summary-detailed",
        "evaluation": "llm-evaluation-detailed",
    }[context.analysis_level]
    result = execute_hogql_query(
        query_type="ClusteringFirstRunPreparedItems",
        query=parse_select(
            """
            SELECT DISTINCT arrayElement(splitByString('::', document_id), 1)
            FROM raw_document_embeddings
            WHERE timestamp >= {start} AND timestamp < {end}
                AND product = 'llm-analytics' AND document_type = {document_type}
                AND JSONExtractString(metadata, 'job_id') = {job_id}
                AND length(embedding) > 0
            LIMIT {limit}
            """
        ),
        placeholders={
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "document_type": ast.Constant(value=document_type),
            "job_id": ast.Constant(value=context.job_id),
            "limit": ast.Constant(value=FIRST_RUN_SAMPLE_LIMIT),
        },
        team=Team.objects.get(id=team_id),
        workload=Workload.OFFLINE,
    )
    return len(result.results or [])


def count_eligible_evaluations(team_id: int, context: ClusteringRunContext, start: datetime, end: datetime) -> int:
    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=context.user_id, is_active=True)
    filters = [property_to_expr(f, team) for f in context.event_filters]
    result = execute_hogql_query(
        query_type="ClusteringFirstRunEligibleEvaluations",
        query=parse_select(
            """
            SELECT DISTINCT uuid FROM events
            WHERE event = '$ai_evaluation' AND timestamp >= {start} AND timestamp < {end}
                AND (isNull(properties.$ai_evaluation_result_type) OR properties.$ai_evaluation_result_type != 'numeric')
                AND (isNull(properties.$ai_evaluation_result_type) OR properties.$ai_evaluation_result_type != 'categorical')
                AND {filters}
            LIMIT {limit}
            """
        ),
        placeholders={
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "filters": ast.And(exprs=filters) if filters else ast.Constant(value=True),
            "limit": ast.Constant(value=context.minimum),
        },
        team=team,
        user=user,
        user_access_control=UserAccessControl(user, team),
        workload=Workload.OFFLINE,
    )
    return len(result.results or [])
