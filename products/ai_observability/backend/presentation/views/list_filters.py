from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from posthog.api.mixins import ValidatedRequest
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.permissions import scopes_caller_lacks

from ...facade import api
from .property_filters import QUERY_SCOPE, QUERY_SCOPE_REQUIRED, PropertyFiltersField, filters_need_query_scope


def page_limit_field(noun: str, *, default: int, maximum: int) -> serializers.IntegerField:
    return serializers.IntegerField(
        min_value=1,
        max_value=maximum,
        default=default,
        help_text=f"How many {noun} a page holds, from 1 to {maximum}. Defaults to {default}.",
    )


def property_filters_field(listed_when: str) -> PropertyFiltersField:
    return PropertyFiltersField(
        required=False,
        help_text=f"Up to {api.MAX_PROPERTY_FILTERS} property filters as a JSON-encoded list. {listed_when} Supported "
        "types are event, event_metadata, person, session, group, cohort and element, plus hogql, data_warehouse and "
        f"data_warehouse_person_property, which need the {QUERY_SCOPE} scope.",
    )


def search_field(searched: str) -> serializers.CharField:
    return serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text=f"Text to look for in the inputs and outputs of {searched}, ignoring case. Leading and trailing "
        "spaces are ignored, and a blank value searches nothing.",
    )


def person_scope_field(listed: str) -> serializers.UUIDField:
    return serializers.UUIDField(
        required=False,
        help_text=f"Lists only {listed} belong to the person with this UUID.",
    )


def group_scope_field(listed: str) -> serializers.CharField:
    return serializers.CharField(
        required=False,
        help_text=f"Lists only {listed} belong to the group with this key. Send it with group_type_index.",
    )


class TraceDateRangeQuerySerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        help_text="Start of the date range, as an ISO 8601 date or datetime, a relative date such as -24h or -7d, "
        "or all for the past year. Defaults to seven days ago.",
    )
    date_to = serializers.CharField(
        required=False,
        help_text="End of the date range, as an ISO 8601 date or datetime or a relative date. A date without a time "
        "includes that whole day. Defaults to now.",
    )
    filter_test_accounts = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Whether to leave out events from the project's test accounts. Defaults to the project's own "
        "setting for filtering test accounts.",
    )


class ListFilterQuerySerializer(TraceDateRangeQuerySerializer):
    """The filter and paging params that the traces list and the sessions list share. Each list adds the params whose
    help names what it lists, `properties`, `search`, `person_id`, `group_key` and `limit`, through the field functions
    above."""

    group_type_index = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=GROUP_TYPES_LIMIT - 1,
        help_text=f"The index of the group type that group_key belongs to, from 0 to {GROUP_TYPES_LIMIT - 1}. "
        "Send it with group_key.",
    )
    cursor = serializers.CharField(
        required=False,
        help_text="The nextCursor of the previous page, to read the page after it. Leave it out for the first page.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("group_key" in attrs) != ("group_type_index" in attrs):
            raise serializers.ValidationError("Send group_key and group_type_index together.")
        return attrs


_PAGE_POSITION_PARAMS = ("cursor", "before_cursor", "around")


def check_one_page_position(attrs: dict[str, Any]) -> None:
    if sum(name in attrs for name in _PAGE_POSITION_PARAMS) > 1:
        raise serializers.ValidationError("Send only one of cursor, before_cursor and around.")


def selection_filters(query: dict[str, Any]) -> dict[str, Any]:
    """The `TraceSelection` arguments that the shared filter params set."""
    return {
        "properties": query.get("properties", ()),
        "filter_test_accounts": query["filter_test_accounts"],
        "search": query.get("search") or None,
        "person_id": str(query["person_id"]) if "person_id" in query else None,
        "group": api.TraceGroupScope(key=query["group_key"], type_index=query["group_type_index"])
        if "group_key" in query
        else None,
    }


def require_query_scope_for_filters(request: ValidatedRequest, query: dict[str, Any]) -> None:
    if filters_need_query_scope(query.get("properties", ())) and scopes_caller_lacks(request, [QUERY_SCOPE]):
        raise PermissionDenied(QUERY_SCOPE_REQUIRED)
