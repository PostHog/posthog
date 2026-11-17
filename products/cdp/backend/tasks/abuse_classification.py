from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.scoping_audit import skip_team_scope_audit

from products.cdp.backend.abuse import shadow
from products.cdp.backend.models.hog_functions.hog_function import HogFunction


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def classify_hog_function_for_abuse(team_id: int, hog_function_id: str) -> None:
    hog_function = (
        HogFunction.objects.select_related("team__organization")
        .filter(team_id=team_id, id=hog_function_id, deleted=False, type__in=shadow.CLASSIFIED_TYPES)
        .first()
    )
    if hog_function is not None:
        shadow.classify_if_due(hog_function)
