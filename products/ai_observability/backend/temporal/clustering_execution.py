from temporalio.exceptions import ApplicationError


def require_current_job(team_id: int, job_id: str, job_scope: str) -> str:
    from ..facade.api import is_current_clustering_job

    if not is_current_clustering_job(team_id, job_id, job_scope):
        raise ApplicationError("Clustering is disabled or the job has changed", non_retryable=True)
    return job_scope
