from products.customer_analytics.backend.logic.account_property_coordination import record_account_property_publication
from products.customer_analytics.backend.models import AccountPropertySyncRequest, CustomPropertySyncRun


def get_protected_account_property_jobs(*, team_id: int, saved_query_id: str) -> frozenset[str]:
    requests = AccountPropertySyncRequest.objects.for_team(team_id).filter(
        saved_query_id=saved_query_id, status__in=["pending", "running"]
    )
    runs = CustomPropertySyncRun.objects.for_team(team_id).filter(
        saved_query_id=saved_query_id, status="running", job_id__isnull=False
    )
    return frozenset(requests.values_list("job_id", flat=True)) | frozenset(
        job_id for job_id in runs.values_list("job_id", flat=True) if job_id is not None
    )


__all__ = ["get_protected_account_property_jobs", "record_account_property_publication"]
