from typing import Optional

from rest_framework import request

from posthog.constants import ENTITY_ID, ENTITY_MATH, ENTITY_TYPE
from posthog.models import Entity


def get_target_entity(request: request.Request) -> Entity:
    entity_id = request.GET.get(ENTITY_ID)
    entity_type = request.GET.get(ENTITY_TYPE)
    entity_math = request.GET.get(ENTITY_MATH, None)

    if entity_id and entity_type:
        return Entity({"id": entity_id, "type": entity_type, "math": entity_math})
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


def get_token(data, request) -> Optional[str]:
    if request.method == "GET":
        if request.GET.get("token"):
            return request.GET.get("token")  # token passed as query param
        if request.GET.get("api_key"):
            return request.GET.get("api_key")  # api_key passed as query param
    if request.POST.get("api_key"):
        return request.POST["api_key"]
    if request.POST.get("token"):
        return request.POST["token"]
    if data:
        if isinstance(data, list):
            data = data[0]  # Mixpanel Swift SDK
        if isinstance(data, dict):
            if data.get("$token"):
                return data["$token"]  # JS identify call
            if data.get("token"):
                return data["token"]  # JS reloadFeatures call
            if data.get("api_key"):
                return data["api_key"]  # server-side libraries like posthog-python and posthog-ruby
            if data.get("properties") and data["properties"].get("token"):
                return data["properties"]["token"]  # JS capture call
    return None


# Support test_[apiKey] for users with multiple environments
def clean_token(token):
    is_test_environment = token.startswith("test_")
    token = token[5:] if is_test_environment else token
    return token, is_test_environment
