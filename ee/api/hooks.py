from typing import cast
from urllib.parse import urlparse

from django.conf import settings
from rest_framework import exceptions, serializers, viewsets

from ee.models.hook import Hook
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User


class HookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hook
        fields = ("id", "created", "updated", "event", "target", "resource_id", "team")
        read_only_fields = ("team",)

    def validate_event(self, event):
        if event not in settings.HOOK_EVENTS:
            raise exceptions.ValidationError(detail=f"Unexpected event {event}")
        return event

    def validate_target(self, target):
        if not valid_domain(target):
            raise exceptions.ValidationError(detail=f"'hooks.zapier.com' is the only allowed target domain")
        return target


class HookViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Retrieve, create, update or destroy REST hooks.
    """

    scope_object = "webhook"
    # NOTE: This permissions is needed for Zapier calls but we don't want to expose it in the API docs until
    # it is able to support more than Zapier
    hide_api_docs = True
    queryset = Hook.objects.all()
    ordering = "-created_at"
    serializer_class = HookSerializer

    def perform_create(self, serializer):
        user = cast(User, self.request.user)
        serializer.save(user=user, team_id=self.team_id)


def valid_domain(url) -> bool:
    target_domain = urlparse(url).netloc
    return target_domain == "hooks.zapier.com"
