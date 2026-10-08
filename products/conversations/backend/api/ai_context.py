from __future__ import annotations

from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import TeamMemberLightManagementPermission

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.conversations.backend.ai.ticket_context import ACCOUNT_TARGET_TYPE, MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS
from products.customer_analytics.backend.facade.api import (
    get_custom_property_definition_target_type,
    list_custom_property_definitions,
)

# One bounded read, not a paging loop: each facade call repeats the count, the workflow
# reference scan and the source enrichment, so paging a large team costs several full scans
# for a picker that only ever shows a short list.
MAX_ACCOUNT_PROPERTY_OPTIONS = 500


class AIContextAccountPropertySerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Customer analytics account property definition id.")
    name = serializers.CharField(help_text="Display name of the account property.")


def list_account_property_options(team_id: int, user_access_control: UserAccessControl) -> list[dict[str, object]]:
    page, _ = list_custom_property_definitions(
        team_id,
        offset=0,
        limit=MAX_ACCOUNT_PROPERTY_OPTIONS,
        user_access_control=user_access_control,
        exclude_group_targets=True,
        target_type=ACCOUNT_TARGET_TYPE,
    )
    return [{"id": item.id, "name": item.name} for item in page if item.id is not None and item.name]


class AIContextAccountPropertiesViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    # Same authorization as the Customer analytics definition list this reads from: the names
    # and ids are account data, so project membership alone is not enough.
    scope_object = "account"
    permission_classes = [TeamMemberLightManagementPermission]
    pagination_class = None
    serializer_class = AIContextAccountPropertySerializer

    @extend_schema(
        responses=AIContextAccountPropertySerializer(many=True),
        description=(
            "Account-target Customer analytics properties that can be included in AI reply context. "
            f"Capped at the first {MAX_ACCOUNT_PROPERTY_OPTIONS} properties by name."
        ),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(
            list_account_property_options(self.team.id, self.user_access_control),
            many=True,
        )
        return Response(serializer.data)


def validate_ai_context_conversations_settings(value: dict, *, team_id: int | None) -> dict:
    """Normalize ai_context_account_property_ids. Raises DRF ValidationError.

    ``team_id`` is ``None`` while a team is being created. The shape checks still run, but a team
    that does not exist yet owns no property definition, so every id is dropped."""
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

    if not ids or team_id is None:
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
