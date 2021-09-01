import re
from typing import Optional, Tuple

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

    new_offset = str(offset + page_size)

    if "offset" in next_url:
        next_url = next_url[1:]
        next_url = next_url.replace(f"offset={str(offset)}", f"offset={new_offset}")
    else:
        next_url = request.build_absolute_uri(
            "{}{}offset={}".format(next_url, "&" if "?" in next_url else "?", offset + page_size)
        )
    return next_url


OFFSET_REGEX = re.compile(r"([&?]offset=)(\d+)")


def format_offset_absolute_url(request: request.Request, offset: int):
    url_to_format = request.get_raw_uri()

    if not url_to_format:
        return None

    if OFFSET_REGEX.match(url_to_format):
        url_to_format = OFFSET_REGEX.sub(fr"\g<1>{offset}", url_to_format)
    else:
        url_to_format = url_to_format + ("&" if "?" in url_to_format else "?") + f"offset={offset}"

    return url_to_format


def get_token(data, request) -> Tuple[Optional[str], bool]:
    token = None
    if request.method == "GET":
        if request.GET.get("token"):
            token = request.GET.get("token")  # token passed as query param
        elif request.GET.get("api_key"):
            token = request.GET.get("api_key")  # api_key passed as query param

    if not token:
        if request.POST.get("api_key"):
            token = request.POST["api_key"]
        elif request.POST.get("token"):
            token = request.POST["token"]
        elif data:
            if isinstance(data, list):
                data = data[0]  # Mixpanel Swift SDK
            if isinstance(data, dict):
                if data.get("$token"):
                    token = data["$token"]  # JS identify call
                elif data.get("token"):
                    token = data["token"]  # JS reloadFeatures call
                elif data.get("api_key"):
                    token = data["api_key"]  # server-side libraries like posthog-python and posthog-ruby
                elif data.get("properties") and data["properties"].get("token"):
                    token = data["properties"]["token"]  # JS capture call

    if token:
        return clean_token(token)
    return None, False


# Support test_[apiKey] for users with multiple environments
def clean_token(token):
    is_test_environment = token.startswith("test_")
    token = token[5:] if is_test_environment else token
    return token, is_test_environment
