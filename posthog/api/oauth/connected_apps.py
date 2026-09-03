import uuid
from datetime import datetime
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import SessionAuthentication
from posthog.models.oauth import (
    OAuthApplication,
    live_oauth_access_tokens,
    live_oauth_refresh_tokens,
    revoke_oauth_session,
)
from posthog.models.user import User


class ConnectedAppSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The OAuth application ID")
    name = serializers.CharField(help_text="The application name")
    logo_uri = serializers.URLField(allow_null=True, help_text="URL to the application's logo")
    scopes = serializers.ListField(child=serializers.CharField(), help_text="Scopes granted to this application")
    authorized_at = serializers.DateTimeField(help_text="When the user first authorized this application")
    is_verified = serializers.BooleanField(help_text="Whether this application has been verified by PostHog")
    is_first_party = serializers.BooleanField(help_text="Whether this is a first-party PostHog application")


@extend_schema(tags=["oauth"])
class ConnectedAppsViewSet(viewsets.ViewSet):
    """
    ViewSet for listing and revoking OAuth applications connected to the current user.
    """

    authentication_classes = [SessionAuthentication]
    http_method_names = ["get", "post"]

    @extend_schema(
        responses={200: ConnectedAppSerializer(many=True)},
        summary="List connected OAuth applications",
        description=(
            "Returns all OAuth applications that can currently act as the requesting user, "
            "whether they hold an unexpired access token or an unrevoked refresh token."
        ),
    )
    def list(self, request: Request) -> Response:
        user = cast(User, request.user)
        app_map: dict[str, dict] = {}

        def record(application_id: uuid.UUID, created: datetime, scope: str | None) -> None:
            entry = app_map.setdefault(str(application_id), {"authorized_at": created, "scopes": set()})
            if created < entry["authorized_at"]:
                entry["authorized_at"] = created
            if scope:
                entry["scopes"].update(scope.split())

        for access_token in live_oauth_access_tokens(user).values("application_id", "scope", "created"):
            record(access_token["application_id"], access_token["created"], access_token["scope"])

        # An unrevoked refresh token is standing access even in the windows where the app holds no
        # unexpired access token, so listing on access tokens alone hides a connection the user
        # still needs to see and revoke. Scope comes from the access token the refresh token was
        # issued alongside, which survives its own expiry because `clear_expired` only deletes
        # access tokens that have no refresh token.
        for refresh_token in live_oauth_refresh_tokens(user).values("application_id", "created", "access_token__scope"):
            record(refresh_token["application_id"], refresh_token["created"], refresh_token["access_token__scope"])

        applications = OAuthApplication.objects.filter(id__in=app_map.keys())

        results = []
        for app in applications:
            app_data = app_map[str(app.id)]
            results.append(
                {
                    "id": app.id,
                    "name": app.name,
                    "logo_uri": app.logo_uri,
                    "scopes": sorted(app_data["scopes"]),
                    "authorized_at": app_data["authorized_at"],
                    "is_verified": app.is_verified,
                    "is_first_party": app.is_first_party,
                }
            )

        results.sort(key=lambda x: x["authorized_at"], reverse=True)
        serializer = ConnectedAppSerializer(results, many=True)
        return Response(serializer.data)

    @extend_schema(
        responses={204: None},
        summary="Revoke a connected OAuth application",
        description="Revokes all tokens and grants for the specified application for the current user.",
    )
    def revoke(self, request: Request, pk: str | None = None) -> Response:
        user = cast(User, request.user)

        access_token = live_oauth_access_tokens(user).filter(application_id=pk).first()
        if access_token:
            revoke_oauth_session(access_token=access_token)
            return Response(status=status.HTTP_204_NO_CONTENT)

        # Same reason the listing considers refresh tokens: without this fallback, an app the user
        # can see in the list is un-revocable whenever its access token has lapsed, which is most
        # of the time for a connection that refreshes on demand. Either entry point sweeps the
        # whole (user, application) pair, so the outcome is identical.
        refresh_token = live_oauth_refresh_tokens(user).filter(application_id=pk).first()
        if refresh_token:
            revoke_oauth_session(refresh_token=refresh_token)
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(
            {"detail": "No active connection found for this application."},
            status=status.HTTP_404_NOT_FOUND,
        )
