from rest_framework import request

from posthog.constants import ENTITY_ID, ENTITY_TYPE
from posthog.models import Entity


def get_target_entity(request: request.Request) -> Entity:
    entity_id = request.GET.get(ENTITY_ID)
    entity_type = request.GET.get(ENTITY_TYPE)

    if entity_id and entity_type:
        return Entity({"id": entity_id, "type": entity_type})
    else:
        raise ValueError("An entity must be provided for target entity to be determined")
