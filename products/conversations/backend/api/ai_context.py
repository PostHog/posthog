from __future__ import annotations

from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.conversations.backend.ai.ticket_context import ACCOUNT_TARGET_TYPE, MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS
from products.customer_analytics.backend.facade.api import (
    get_custom_property_definition_target_type,
    list_custom_property_definitions,
)

_LIST_PAGE_SIZE = 200


class AIContextAccountPropertySerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Customer analytics account property definition id.")
    name = serializers.CharField(help_text="Display name of the account property.")


def list_account_property_options(team_id: int, user_access_control: UserAccessControl) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    while True:
        page, total = list_custom_property_definitions(
            team_id,
            offset=offset,
            limit=_LIST_PAGE_SIZE,
            user_access_control=user_access_control,
            exclude_group_targets=True,
        )
        for item in page:
            if item.target_type != ACCOUNT_TARGET_TYPE or item.id is None or not item.name:
                continue
            rows.append({"id": item.id, "name": item.name})
        offset += _LIST_PAGE_SIZE
        if offset >= total or not page:
            break
    return rows


class AIContextAccountPropertiesViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "project"
    pagination_class = None
    serializer_class = AIContextAccountPropertySerializer

    @extend_schema(
        responses=AIContextAccountPropertySerializer(many=True),
        description="Account-target Customer analytics properties that can be included in AI reply context.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(
            list_account_property_options(self.team.id, self.user_access_control),
            many=True,
        )
        return Response(serializer.data)


def validate_ai_context_conversations_settings(value: dict, *, team_id: int) -> dict:
    """Normalize ai_context_account_property_ids. Raises DRF ValidationError."""
    if "ai_context_account_property_ids" not in value:
        return value
    raw = value.get("ai_context_account_property_ids")
    if raw is None:
        value["ai_context_account_property_ids"] = []
        return value
    if not isinstance(raw, list):
        raise serializers.ValidationError({"ai_context_account_property_ids": "Must be a list of property ids."})

    ids: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise serializers.ValidationError(
                {"ai_context_account_property_ids": "Each property id must be a UUID string."}
            )
        try:
            parsed = str(UUID(item))
        except ValueError as exc:
            raise serializers.ValidationError(
                {"ai_context_account_property_ids": "Each property id must be a UUID string."}
            ) from exc
        if parsed in seen:
            continue
        seen.add(parsed)
        ids.append(parsed)
        if len(ids) >= MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS:
            break

    if not ids:
        value["ai_context_account_property_ids"] = []
        return value

    try:
        kept = [
            item for item in ids if get_custom_property_definition_target_type(team_id, item) == ACCOUNT_TARGET_TYPE
        ]
    except Exception as exc:
        raise serializers.ValidationError(
            {"ai_context_account_property_ids": "Couldn't validate account properties."}
        ) from exc
    value["ai_context_account_property_ids"] = kept
    return value
