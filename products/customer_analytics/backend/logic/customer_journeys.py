from django.db.models import QuerySet

from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import ResourceType
from products.authorization.backend.presentation.querysets import filter_queryset
from products.customer_analytics.backend.models import CustomerJourney


def customer_journeys_queryset(team_id: int, *, subject: Subject | None = None) -> QuerySet[CustomerJourney]:
    journeys = CustomerJourney.objects.filter(team_id=team_id).order_by("created_at")
    if subject is None:
        return journeys
    return filter_queryset(
        journeys, resource=Resource(type=ResourceType.CUSTOMER_JOURNEY, project_id=team_id), subject=subject
    )
