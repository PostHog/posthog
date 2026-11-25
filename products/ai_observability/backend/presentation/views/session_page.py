from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers

from ...facade import api

SESSION_PAGE_BAD_REQUEST = OpenApiResponse(description="The session IDs are missing or too many.")


class SessionPageRequestSerializer(serializers.Serializer):
    session_ids = serializers.ListField(
        child=serializers.CharField(trim_whitespace=False, max_length=api.SESSION_ID_MAX_LENGTH),
        min_length=1,
        max_length=api.SESSION_LIST_MAX_LIMIT,
        help_text=f"The IDs of the sessions on a page of the list, from 1 to {api.SESSION_LIST_MAX_LIMIT}. Items come "
        f"back in this order, once per ID. A session ID is at most {api.SESSION_ID_MAX_LENGTH} characters, the longest "
        "the sessions list hands out.",
    )
