from typing import List, Dict

from celery import shared_task
from django.db.models import UUIDField
from django.utils import timezone

from posthog.clickhouse.client.connection import Workload
from posthog.client import sync_execute
from posthog.models import Survey


def _get_surveys_response_counts(surveys_ids: List[UUIDField]) -> Dict[str, int]:
    data = sync_execute(
        """
        SELECT JSONExtractString(properties, '$survey_id') as survey_id, count()
        FROM events
        WHERE event = 'survey sent' AND survey_id in %(surveys_ids)s
        GROUP BY survey_id
    """,
        {"surveys_ids": surveys_ids},
        workload=Workload.OFFLINE,
    )

    counts = {}
    for survey_id, count in data:
        counts[survey_id] = count
    return counts


@shared_task(ignore_result=True)
def stop_surveys_reached_target() -> None:
    surveys = Survey.objects.exclude(responses_limit__isnull=True).only("id", "responses_limit")
    if not surveys:
        return

    surveys_ids = [survey.id for survey in surveys]
    response_counts = _get_surveys_response_counts(surveys_ids)
    for survey in surveys:
        survey_id = str(survey.id)
        if survey_id not in response_counts:
            continue

        assert survey.responses_limit is not None
        response_count = response_counts[survey_id]
        if response_count < survey.responses_limit:
            continue

        survey.end_date = timezone.now()
        survey.responses_limit = None
        survey.save(update_fields=["end_date", "responses_limit"])
