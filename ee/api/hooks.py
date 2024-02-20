from typing import cast
from django.db.models import QuerySet

from django.conf import settings
from rest_framework import exceptions, serializers, viewsets

from ee.models.hook import Hook
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User


class HookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hook
        fields = ("id", "created", "updated", "event", "target", "resource_id", "team", "format_text")
        read_only_fields = ("team",)

    def validate_event(self, event):
        if event not in settings.HOOK_EVENTS:
            raise exceptions.ValidationError(detail=f"Unexpected event {event}")
        return event


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

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()

        if self.action == "list":
            if self.request.GET.get("resource_id", None):
                queryset = queryset.filter(resource_id=self.request.GET["resource_id"])

        return queryset

    def perform_create(self, serializer):
        user = cast(User, self.request.user)
        serializer.save(user=user, team_id=self.team_id)
