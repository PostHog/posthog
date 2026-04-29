from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import SessionAuthentication
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, revoke_oauth_session


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
        description="Returns all OAuth applications that have active (non-expired) access tokens for the current user.",
    )
    def list(self, request: Request) -> Response:
        now = timezone.now()

        tokens = OAuthAccessToken.objects.filter(
            user=request.user,
            application__isnull=False,
            expires__gt=now,
        ).values("application_id", "scope", "created")

        app_map: dict[str, dict] = {}
        for token in tokens:
            app_id = str(token["application_id"])
            if app_id not in app_map:
                app_map[app_id] = {"authorized_at": token["created"], "scopes": set()}
            else:
                if token["created"] < app_map[app_id]["authorized_at"]:
                    app_map[app_id]["authorized_at"] = token["created"]
            if token["scope"]:
                app_map[app_id]["scopes"].update(token["scope"].split())

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
        now = timezone.now()

        access_token = OAuthAccessToken.objects.filter(
            user=request.user,
            application_id=pk,
            expires__gt=now,
        ).first()

        if not access_token:
            return Response(
                {"detail": "No active connection found for this application."},
                status=status.HTTP_404_NOT_FOUND,
            )

        revoke_oauth_session(access_token=access_token)

        return Response(status=status.HTTP_204_NO_CONTENT)
