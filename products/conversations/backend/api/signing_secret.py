from __future__ import annotations

from typing import Any, cast

from django.db import transaction
from django.utils import timezone

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
from posthog.models.team import Team
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
    previous_secret_valid_until = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Until when the previous secret keeps verifying after a rotation, or null when no grace window is active.",
    )


def _serializer_payload(row: SigningSecret | None) -> dict[str, Any]:
    return {
        "secret": row.secret if row else None,
        "updated_at": row.updated_at if row else None,
        "previous_secret_valid_until": row.previous_secret_valid_until if row and row.previous_secret_active else None,
    }


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
        serializer = SigningSecretSerializer(_serializer_payload(row))
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses=SigningSecretSerializer,
        description="Generate a new signing secret. The previous secret keeps verifying identity hashes for 48 hours, then expires.",
    )
    @action(methods=["POST"], detail=False)
    def rotate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # One transaction: a credential change without its audit row must not commit.
        with transaction.atomic():
            # Locked get_or_create: two concurrent requests must serialize, or the loser
            # overwrites the winner's secret right after it was shown to the winner.
            # The loser then sees the winner's row and treats it as a rotation, so the
            # winner's secret survives through the grace window.
            row, created = (
                SigningSecret.objects.for_team(self.team_id)
                .select_for_update()
                .get_or_create(
                    team_id=self.team_id,
                    defaults={"secret": generate_random_token(), "rotated_independently": True},
                )
            )
            old_secret = None if created else row.secret
            if not created:
                # Grace only for a secret that was a trusted verification candidate.
                # A stale mirror holds a retired key the staleness guard excluded;
                # granting it grace would resurrect a revoked credential.
                has_legacy = bool(self.team.secret_api_token or self.team.secret_api_token_backup)
                old_secret_trusted = (
                    row.rotated_independently or not has_legacy or row.secret == self.team.secret_api_token
                )
                if old_secret_trusted:
                    row.previous_secret = row.secret
                    row.previous_secret_rotated_at = timezone.now()
                else:
                    row.previous_secret = None
                    row.previous_secret_rotated_at = None
                row.secret = generate_random_token()
                row.rotated_independently = True
                row.save()
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
                            action="created" if created else "changed",
                            field="conversations_signing_secret",
                            before=mask_key_value(old_secret) if old_secret else None,
                            after=mask_key_value(row.secret),
                        )
                    ],
                ),
            )
        serializer = SigningSecretSerializer(_serializer_payload(row))
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses=SigningSecretSerializer,
        description="End the rotation grace window now: the previous secret stops verifying immediately. Use it when the replaced secret may be compromised, or once every server runs the new one.",
    )
    @action(methods=["POST"], detail=False)
    def expire_previous(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        with transaction.atomic():
            # Team lock first: a legacy rotation racing this expiry would rewrite the
            # backup column between the comparison below and the deletion.
            locked_team = Team.objects.select_for_update(no_key=True).get(pk=self.team_id)
            row = SigningSecret.objects.for_team(self.team_id).select_for_update().first()
            if row and row.previous_secret:
                expired = row.previous_secret
                row.previous_secret = None
                row.previous_secret_rotated_at = None
                row.save(update_fields=["previous_secret", "previous_secret_rotated_at"])
                # A legacy rotation leaves the same credential in the backup column,
                # where it keeps verifying (and authenticating) while the legacy
                # verifiers are on. Expiry is a revocation, so it must cover that copy.
                if locked_team.secret_api_token_backup == expired:
                    locked_team.delete_secret_token_backup_and_save(
                        user=cast(User, request.user), is_impersonated_session=is_impersonated(request)
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
                                action="deleted",
                                field="conversations_signing_secret_previous",
                                before=mask_key_value(expired),
                                after=None,
                            )
                        ],
                    ),
                )
        serializer = SigningSecretSerializer(_serializer_payload(row))
        return Response(serializer.data)
