from django.conf import settings
from rest_framework import exceptions, serializers, viewsets

from posthog.models.hook import Hook


class HookSerializer(serializers.ModelSerializer):
    def validate_event(self, event):
        if event not in settings.HOOK_EVENTS:
            raise exceptions.ValidationError(detail=f"Unexpected event {event}")
        return event

    class Meta:
        model = Hook
        fields = "__all__"
        read_only_fields = ("team", "user")


class HookViewSet(viewsets.ModelViewSet):
    """
    Retrieve, create, update or destroy webhooks.
    """

    queryset = Hook.objects.all()
    model = Hook
    serializer_class = HookSerializer

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(user=user, team=user.team_set.get())
