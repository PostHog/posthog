from django.conf import settings
from django.db.models import query
from rest_framework import exceptions, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from ee.models.hook import Hook
from posthog.permissions import OrganizationMemberPermissions
from posthog.utils import StructuredViewSetMixin


class HookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hook
        fields = ("id", "created", "updated", "event", "target", "resource_id", "team")
        read_only_fields = ("team",)

    def validate_event(self, event):
        if event not in settings.HOOK_EVENTS:
            raise exceptions.ValidationError(detail=f"Unexpected event {event}")
        return event

    def create(self, validated_data):
        instance = super().create(validated_data)
        instance.user = self.context["request"].user
        instance.team_id = self.context["team_id"]
        return instance


class HookViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Retrieve, create, update or destroy webhooks.
    """

    queryset = Hook.objects.all()
    serializer_class = HookSerializer
    ordering = "-created_at"
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions]
