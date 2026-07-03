"""Proactive product enablement for self-driving Signals setup.

Turns PostHog products ON so their signal sources have data to read. The wizard
calls this (via the `products-enable` MCP tool) before it enables sources, so a
freshly-instrumented project isn't left with empty inboxes.

Exposed under a narrow `product_enablement:write` scope rather than `project:write`:
the caller only names which products; the server owns each recipe (the primary
toggle plus conservative companion defaults), so a caller can never weaken masking
or delete the project. Adding a product later = one entry in `RECIPES`.
"""

import secrets
from collections.abc import Callable
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.team import TEAM_CONFIG_ADMIN_FIELDS_SET
from posthog.helpers.impersonation import is_impersonated
from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.activity_log import Detail, dict_changes_between, log_activity
from posthog.models.team import Team

# Written only when the team has none set. posthog-js already masks inputs + passwords
# by default, so this just pins that floor — page text stays visible for Signals to read.
REPLAY_MASKING_FLOOR = {"maskAllInputs": True}

# Sets the primary toggle (always) + companion defaults (only if unset, never clobbering
# user config). Adds touched field names to `touched`; returns "enabled" or "already_enabled".
Recipe = Callable[[Team, set[str]], str]


def _enable_session_replay(team: Team, touched: set[str]) -> str:
    if team.session_recording_masking_config is None:
        team.session_recording_masking_config = dict(REPLAY_MASKING_FLOOR)
        touched.add("session_recording_masking_config")
    if team.session_recording_opt_in:
        return "already_enabled"
    team.session_recording_opt_in = True
    touched.add("session_recording_opt_in")
    return "enabled"


def _enable_error_tracking(team: Team, touched: set[str]) -> str:
    if team.autocapture_exceptions_opt_in:
        return "already_enabled"
    team.autocapture_exceptions_opt_in = True
    touched.add("autocapture_exceptions_opt_in")
    return "enabled"


def _enable_conversations(team: Team, touched: set[str]) -> str:
    if team.conversations_enabled:
        return "already_enabled"
    team.conversations_enabled = True
    touched.add("conversations_enabled")
    # Mirror handle_conversations_token_on_update (posthog/api/team.py): mint a widget
    # token but leave the widget off — tickets need a connected channel (the report CTA).
    settings = dict(team.conversations_settings or {})
    if not settings.get("widget_public_token"):
        settings["widget_public_token"] = secrets.token_urlsafe(32)
        team.conversations_settings = settings
        touched.add("conversations_settings")
    return "enabled"


RECIPES: dict[str, Recipe] = {
    "session_replay": _enable_session_replay,
    "error_tracking": _enable_error_tracking,
    "conversations": _enable_conversations,
}


class ProductEnablementSerializer(serializers.Serializer):
    products = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(RECIPES.keys())),
        allow_empty=False,
        min_length=1,
        help_text="Products to turn on for this project, each enabled with server-owned conservative defaults.",
    )


class ProductEnablementResultSerializer(serializers.Serializer):
    results = serializers.DictField(
        child=serializers.CharField(),
        help_text='Per requested product: "enabled" (just turned on) or "already_enabled".',
    )


class ProductEnablementViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "product_enablement"

    @extend_schema(
        request=ProductEnablementSerializer,
        responses={200: ProductEnablementResultSerializer},
        # Route the generated client to frontend/src/generated/core/ — this is a core
        # endpoint, not part of any product folder.
        extensions={"x-product": "core"},
    )
    def create(self, request, *args, **kwargs):
        serializer = ProductEnablementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        team = self.team
        before = team.__dict__.copy()
        touched: set[str] = set()
        # dict.fromkeys dedupes while preserving the caller's order.
        results = {
            product: RECIPES[product](team, touched) for product in dict.fromkeys(serializer.validated_data["products"])
        }

        # conversations + replay masking are admin-only on the normal Team-update API; replicate that
        # gate so this endpoint can't be a bypass (error_tracking + the replay opt-in stay member-safe).
        admin_fields = touched & TEAM_CONFIG_ADMIN_FIELDS_SET
        if admin_fields:
            level = self.user_permissions.team(team).effective_membership_level
            if level is None or level < OrganizationMembership.Level.ADMIN:
                raise PermissionDenied(
                    "Only project admins can enable products that change these settings: "
                    + ", ".join(sorted(admin_fields))
                )

        if touched:
            team.save(update_fields=sorted(touched))
            # Audit the enable like the Team-update API does; drop conversations_settings so the
            # minted widget token never lands in the activity log.
            changes = [
                change
                for change in dict_changes_between("Team", before, team.__dict__, use_field_exclusions=True)
                if change.field != "conversations_settings"
            ]
            log_activity(
                organization_id=team.organization_id,
                team_id=team.pk,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
                scope="Team",
                item_id=team.pk,
                activity="updated",
                detail=Detail(name=str(team.name), changes=changes),
            )

        return Response({"results": results}, status=status.HTTP_200_OK)
