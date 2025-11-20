"""
REST API for notification preferences.
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.notification_preference import NotificationPreference
from posthog.notifications.preference_serializers import NotificationPreferenceSerializer


class NotificationPreferenceViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for user notification preferences.

    Endpoints:
    - GET /api/projects/{project_id}/notification_preferences/ - List user's preferences
    - POST /api/projects/{project_id}/notification_preferences/ - Create/update preference
    - DELETE /api/projects/{project_id}/notification_preferences/{id}/ - Delete preference
    - POST /api/projects/{project_id}/notification_preferences/reset/ - Reset all to defaults
    """

    scope_object = "INTERNAL"
    serializer_class = NotificationPreferenceSerializer
    permission_classes = [IsAuthenticated]
    queryset = NotificationPreference.objects.all()

    def safely_get_queryset(self, queryset):
        """Filter preferences for current user."""
        return queryset.filter(user=self.request.user)

    def get_serializer_context(self):
        """Add team to serializer context."""
        context = super().get_serializer_context()
        context["team"] = self.team
        return context

    @action(detail=False, methods=["post"])
    def reset(self, request, *args, **kwargs):
        """
        Reset all preferences to defaults (delete all custom preferences).

        This will make the user receive all notification types (opt-in model).
        """
        count = NotificationPreference.objects.filter(
            user=request.user,
            team=self.team,
        ).delete()[0]

        return Response(
            {"deleted": count, "message": "All preferences reset to defaults"},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"])
    def bulk_update(self, request, *args, **kwargs):
        """
        Bulk update multiple preferences at once.

        Request body:
        {
            "preferences": [
                {"resource_type": "feature_flag", "enabled": true},
                {"resource_type": "alert", "enabled": false},
                ...
            ]
        }
        """
        preferences_data = request.data.get("preferences", [])

        if not isinstance(preferences_data, list):
            return Response(
                {"error": "preferences must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = []
        for pref_data in preferences_data:
            preference, created = NotificationPreference.objects.update_or_create(
                user=request.user,
                team=self.team,
                resource_type=pref_data["resource_type"],
                defaults={"enabled": pref_data["enabled"]},
            )
            updated.append(self.serializer_class(preference).data)

        return Response(
            {"updated": len(updated), "preferences": updated},
            status=status.HTTP_200_OK,
        )
