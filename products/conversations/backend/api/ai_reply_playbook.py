from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.conversations.backend.playbook import (
    DOCS_SOURCE_POSTHOG,
    MAX_CUSTOM_INSTRUCTIONS_CHARS,
    WARNING_CUSTOM_OVERSIZED,
    compose_support_playbook,
)


class AIReplyPlaybookSerializer(serializers.Serializer):
    inherited_instructions = serializers.CharField(
        read_only=True,
        help_text="Repo default instructions, plus the PostHog overlay when docs_source is posthog.",
    )
    custom_instructions = serializers.CharField(
        allow_null=True,
        read_only=True,
        help_text="Team addendum on top of the inherited playbook. Null means the team inherits the default instructions.",
    )
    is_customized = serializers.BooleanField(
        read_only=True,
        help_text="True when a non-empty custom addendum is saved for this team.",
    )
    default_version = serializers.IntegerField(
        read_only=True,
        help_text="Version of the generic default playbook layer currently in the repo.",
    )
    posthog_overlay_version = serializers.IntegerField(
        allow_null=True,
        read_only=True,
        help_text="Version of the PostHog overlay when docs_source is posthog; null otherwise.",
    )
    docs_source = serializers.CharField(
        allow_null=True,
        read_only=True,
        help_text="Documentation source for this team. 'posthog' enables PostHog docs-search and the PostHog overlay.",
    )
    max_chars = serializers.IntegerField(
        read_only=True,
        help_text="Maximum character length for ai_reply_custom_instructions.",
    )


class _SingletonSchema(PostHogAutoSchema):
    """Prevents drf-spectacular from wrapping the ``list`` response in an array.

    A project has one playbook, not a collection of them.
    """

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class AIReplyPlaybookViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    schema = _SingletonSchema()
    scope_object = "project"
    pagination_class = None
    serializer_class = AIReplyPlaybookSerializer

    @extend_schema(
        responses=AIReplyPlaybookSerializer,
        description="Inherited support-reply playbook for this project, plus the team's custom addendum if any.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        settings_dict = self.team.conversations_settings or {}
        raw_docs = settings_dict.get("docs_source")
        docs_source = raw_docs if isinstance(raw_docs, str) else None
        raw_custom = settings_dict.get("ai_reply_custom_instructions")
        custom = raw_custom if isinstance(raw_custom, str) else None
        composed = compose_support_playbook(docs_source=docs_source, custom_instructions=custom)
        serializer = AIReplyPlaybookSerializer(
            {
                "inherited_instructions": composed.inherited_text,
                "custom_instructions": composed.custom_text,
                "is_customized": composed.custom_text is not None,
                "default_version": composed.default_version,
                "posthog_overlay_version": composed.posthog_overlay_version,
                "docs_source": composed.docs_source,
                "max_chars": MAX_CUSTOM_INSTRUCTIONS_CHARS,
            }
        )
        return Response(serializer.data)


def _docs_source_from_settings(value: dict, existing: dict | None) -> str | None:
    if "docs_source" in value:
        raw = value.get("docs_source")
    elif existing is not None:
        raw = existing.get("docs_source")
    else:
        return None
    return raw if isinstance(raw, str) else None


def validate_playbook_conversations_settings(value: dict, *, existing: dict | None = None) -> dict:
    """Normalize playbook keys on conversations_settings. Raises DRF ValidationError."""
    if "docs_source" in value:
        docs_source = value.get("docs_source")
        if docs_source is None or docs_source == "":
            value["docs_source"] = None
        elif isinstance(docs_source, str):
            if docs_source != DOCS_SOURCE_POSTHOG:
                raise serializers.ValidationError({"docs_source": "Must be 'posthog' or null."})
            value["docs_source"] = docs_source
        else:
            raise serializers.ValidationError({"docs_source": "Must be a string or null."})
    if "ai_reply_custom_instructions" in value:
        custom = value.get("ai_reply_custom_instructions")
        if custom is None:
            value["ai_reply_custom_instructions"] = None
        elif isinstance(custom, str):
            stripped = custom.strip()
            if not stripped:
                value["ai_reply_custom_instructions"] = None
            else:
                composed = compose_support_playbook(
                    docs_source=_docs_source_from_settings(value, existing),
                    custom_instructions=stripped,
                )
                if WARNING_CUSTOM_OVERSIZED in composed.warnings:
                    raise serializers.ValidationError(
                        {
                            "ai_reply_custom_instructions": (
                                f"Must be {MAX_CUSTOM_INSTRUCTIONS_CHARS} characters or fewer."
                            )
                        }
                    )
                value["ai_reply_custom_instructions"] = composed.custom_text
        else:
            raise serializers.ValidationError({"ai_reply_custom_instructions": "Must be a string or null."})
    return value
