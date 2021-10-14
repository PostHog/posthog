from typing import cast

from django.conf import settings
from rest_framework import exceptions, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from ee.models.hook import Hook
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.user import User
from posthog.permissions import OrganizationMemberPermissions, TeamMemberAccessPermission


class HookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hook
        fields = ("id", "created", "updated", "event", "target", "resource_id", "team")
        read_only_fields = ("team",)

    def validate_event(self, event):
        if event not in settings.HOOK_EVENTS:
            raise exceptions.ValidationError(detail=f"Unexpected event {event}")
        return event


class HookViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Retrieve, create, update or destroy REST hooks.
    """

    queryset = Hook.objects.all()
    ordering = "-created_at"
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions, TeamMemberAccessPermission]
    serializer_class = HookSerializer

    def perform_create(self, serializer):
        user = cast(User, self.request.user)
        serializer.save(user=user, team_id=self.team_id)
