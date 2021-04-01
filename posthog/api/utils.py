from typing import Optional

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


def format_next_url(request: request.Request, offset: int, page_size: int):
    next_url = request.get_full_path()
    if not next_url:
        return None

    if "offset" in next_url:
        next_url = next_url[1:]
        next_url = next_url.replace("offset=" + str(offset), "offset=" + str(offset + page_size))
    else:
        next_url = request.build_absolute_uri(
            "{}{}offset={}".format(next_url, "&" if "?" in next_url else "?", offset + page_size)
        )
    return next_url
