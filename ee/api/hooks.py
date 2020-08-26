from django.conf import settings
from rest_framework import exceptions, serializers, viewsets

from ee.models.hook import Hook


class HookSerializer(serializers.ModelSerializer):
    def validate_event(self, event):
        if event not in settings.HOOK_EVENTS:
            raise exceptions.ValidationError(detail=f"Unexpected event {event}")
        return event

    class Meta:
        model = Hook
        fields = ("id", "created", "updated", "event", "target", "resource_id", "team")
        read_only_fields = ("team",)


class HookViewSet(viewsets.ModelViewSet):
    """
    Retrieve, create, update or destroy webhooks.
    """

    model = Hook
    serializer_class = HookSerializer

    def get_queryset(self):
        return Hook.objects.filter(user_id=self.request.user.id).order_by("-created_at")

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(user=user, team=user.team_set.get())
