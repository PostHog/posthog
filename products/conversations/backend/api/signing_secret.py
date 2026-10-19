from __future__ import annotations

from typing import Any, cast

from django.db import transaction

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.user import User
from posthog.models.utils import generate_random_token, mask_key_value
from posthog.permissions import TeamMemberStrictManagementPermission, TimeSensitiveActionPermission

from products.conversations.backend.models import SigningSecret


class SigningSecretSerializer(serializers.Serializer):
    secret = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Raw secret used to compute widget identity verification hashes (HMAC). Null until one exists.",
    )
    updated_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the secret last changed, or null when no secret exists yet.",
    )


class _SessionOnlyPermission(BasePermission):
    # "INTERNAL" only rejects scoped tokens; impersonation JWTs would otherwise pass both
    # the scope check and the session-freshness check without carrying a session.
    message = "The signing secret is only available in the web app."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.successful_authenticator, SessionAuthentication)


class _SingletonSchema(PostHogAutoSchema):
    """A project has one signing secret, so ``list`` must not wrap the response in an array."""

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class SigningSecretViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    schema = _SingletonSchema()
    # The raw secret must stay out of reach of scoped tokens: session auth only.
    scope_object = "INTERNAL"
    pagination_class = None
    serializer_class = SigningSecretSerializer
    permission_classes = [_SessionOnlyPermission, TimeSensitiveActionPermission, TeamMemberStrictManagementPermission]

    @extend_schema(
        responses=SigningSecretSerializer,
        description="The signing secret used for widget identity verification in this project.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        row = SigningSecret.objects.for_team(self.team_id).first()
        serializer = SigningSecretSerializer(
            {"secret": row.secret if row else None, "updated_at": row.updated_at if row else None}
        )
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses=SigningSecretSerializer,
        description="Generate a new signing secret. Identity hashes signed with the previous secret stop verifying immediately.",
    )
    @action(methods=["POST"], detail=False)
    def rotate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        old_row = SigningSecret.objects.for_team(self.team_id).first()
        # One transaction: a credential change without its audit row must not commit.
        with transaction.atomic():
            row, _ = SigningSecret.objects.for_team(self.team_id).update_or_create(
                team_id=self.team_id,
                defaults={"secret": generate_random_token(), "rotated_independently": True},
            )
            log_activity(
                organization_id=self.team.organization_id,
                team_id=self.team_id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
                scope="Team",
                item_id=self.team_id,
                activity="updated",
                detail=Detail(
                    name=str(self.team.name),
                    changes=[
                        Change(
                            type="Team",
                            action="created" if old_row is None else "changed",
                            field="conversations_signing_secret",
                            before=mask_key_value(old_row.secret) if old_row else None,
                            after=mask_key_value(row.secret),
                        )
                    ],
                ),
            )
        serializer = SigningSecretSerializer({"secret": row.secret, "updated_at": row.updated_at})
        return Response(serializer.data)
