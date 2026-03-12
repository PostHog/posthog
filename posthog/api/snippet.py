from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.snippet_versioning import resolve_version
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.snippet_config import TeamSnippetConfig


class SnippetVersionPinSerializer(serializers.Serializer):
    snippet_version_pin = serializers.CharField(
        max_length=50,
        allow_null=True,
        allow_blank=True,
        required=False,
        help_text='Version pin: null for latest, "1.358.0" for exact, "1" for major, "1.358" for minor',
    )


class SnippetViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"

    @action(methods=["GET"], detail=False, url_path="resolve")
    def resolve(self, request: Request, *args, **kwargs):
        """Preview what a given pin would resolve to, without saving it."""
        pin = request.query_params.get("pin")
        if pin is None:
            return Response(
                {"error": "pin query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resolved = resolve_version(pin)
        if resolved is None:
            return Response(
                {"error": "Version not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"resolved": resolved})

    @action(methods=["GET"], detail=False, url_path="version")
    def get_version(self, request: Request, *args, **kwargs):
        """Return the team's current version pin and resolved version."""
        snippet_config = get_or_create_team_extension(self.team, TeamSnippetConfig)
        resolved = resolve_version(snippet_config.snippet_version_pin)
        return Response(
            {
                "snippet_version_pin": snippet_config.snippet_version_pin,
                "resolved_version": resolved,
            }
        )

    @get_version.mapping.patch
    def update_version(self, request: Request, *args, **kwargs):
        """Update the team's version pin."""
        serializer = SnippetVersionPinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pin = serializer.validated_data.get("snippet_version_pin")
        # Treat empty string as null (use latest)
        if pin == "":
            pin = None

        # Validate the pin resolves to something real
        if pin is not None:
            resolved = resolve_version(pin)
            if resolved is None:
                return Response(
                    {"error": "Version not found"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        snippet_config = get_or_create_team_extension(self.team, TeamSnippetConfig)
        snippet_config.snippet_version_pin = pin
        snippet_config.save()

        resolved = resolve_version(snippet_config.snippet_version_pin)
        return Response(
            {
                "snippet_version_pin": snippet_config.snippet_version_pin,
                "resolved_version": resolved,
            }
        )
