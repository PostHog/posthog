from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db.models import F

from posthog.warehouse.types import IncrementalFieldType
from posthog.sync import database_sync_to_async


@database_sync_to_async
def aget_external_data_job(team_id, job_id):
    from posthog.warehouse.models import ExternalDataJob

    return ExternalDataJob.objects.get(id=job_id, team_id=team_id)


@database_sync_to_async
def aupdate_job_count(job_id: str, team_id: int, count: int):
    from posthog.warehouse.models import ExternalDataJob

    ExternalDataJob.objects.filter(id=job_id, team_id=team_id).update(rows_synced=F("rows_synced") + count)


def incremental_type_to_initial_value(field_type: IncrementalFieldType) -> int | datetime | date | str:
    if field_type == IncrementalFieldType.Integer or field_type == IncrementalFieldType.Numeric:
        return 0
    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        return datetime(1970, 1, 1, 0, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    if field_type == IncrementalFieldType.Date:
        return date(1970, 1, 1)
    if field_type == IncrementalFieldType.ObjectID:
        return "000000000000000000000000"
