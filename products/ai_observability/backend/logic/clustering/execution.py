from ...models.clustering_job import ClusteringJob
from .eligibility import eligible_clustering_team_ids
from .scope import scope_key


def is_current_job(team_id: int, job_id: str, job_scope: str) -> bool:
    if team_id not in eligible_clustering_team_ids([team_id]):
        return False
    if not job_id:
        return True
    job = ClusteringJob.objects.filter(team_id=team_id, id=job_id, enabled=True).first()
    return job is not None and (not job_scope or job_scope == scope_key(job.analysis_level, job.event_filters))
