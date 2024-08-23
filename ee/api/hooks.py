from typing import cast
from urllib.parse import urlparse

from rest_framework import exceptions, serializers, mixins, viewsets, status
from rest_framework.response import Response

from ee.models.hook import Hook, HOOK_EVENTS
from django.conf import settings
from posthog.api.hog_function import HogFunctionSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.cdp.templates.zapier.template_zapier import template as template_zapier


def hog_functions_enabled(team: Team) -> bool:
    enabled_teams = settings.HOOK_HOG_FUNCTION_TEAMS.split(",")
    return "*" in enabled_teams or str(team.id) in enabled_teams


def create_zapier_hog_function(hook: Hook, serializer_context: dict) -> HogFunction:
    serializer = HogFunctionSerializer(
        data={
            "template_id": template_zapier.id,
            "name": f"Zapier webhook for action {hook.resource_id}",
            "filters": {"actions": [{"id": str(hook.resource_id), "name": "", "type": "actions", "order": 0}]},
            "inputs": {
                "hook": {
                    "value": hook.target.replace("https://hooks.zapier.com/", ""),
                },
                "body": {
                    # NOTE: This is for backwards compatibility with the old webhook format
                    "value": {
                        "hook": {
                            "id": "{eventUuid}",
                            "event": "{event}",
                            "target": "https://hooks.zapier.com/{inputs.hook}",
                        },
                        "data": {
                            "eventUuid": "{event.uuid}",
                            "event": "{event.name}",
                            "teamId": "{project.id}",
                            "distinctId": "{event.distinct_id}",
                            "properties": "{event.properties}",
                            "timestamp": "{event.timestamp}",
                            "person": {"uuid": "{person.uuid}", "properties": "{person.properties}"},
                        },
                    }
                },
            },
            "enabled": True,
            "icon_url": template_zapier.icon_url,
        },
        context=serializer_context,
    )
    serializer.is_valid(raise_exception=True)
    return HogFunction(**serializer.validated_data)


class HookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hook
        fields = ("id", "created", "updated", "event", "target", "resource_id", "team")
        read_only_fields = ("team",)

    def validate_event(self, event):
        if event not in HOOK_EVENTS:
            raise exceptions.ValidationError(detail=f"Unexpected event {event}")
        return event

    def validate_target(self, target):
        if not valid_domain(target):
            raise exceptions.ValidationError(detail=f"'hooks.zapier.com' is the only allowed target domain")
        return target


# NOTE: This is a special API used by zapier. It will soon be deprecated completely in favour of hog functions
class HookViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
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

    def create(self, request, *args, **kwargs):
        if not hog_functions_enabled(self.team):
            return super().create(request, *args, **kwargs)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hook = Hook(**serializer.validated_data)

        hog_function = create_zapier_hog_function(hook, serializer_context=self.get_serializer_context())
        hog_function.save()

        response_serializer = self.get_serializer(
            data={
                "id": hog_function.id,
                "event": serializer.validated_data["event"],
                "target": serializer.validated_data["target"],
                "resource_id": serializer.validated_data.get("resource_id"),
                "team": self.team.id,
            }
        )
        response_serializer.is_valid(raise_exception=False)

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        user = cast(User, self.request.user)
        serializer.save(user=user, team_id=self.team_id)

    def destroy(self, request, *args, **kwargs):
        if not hog_functions_enabled(self.team):
            return super().destroy(request, *args, **kwargs)

        HogFunction.objects.filter(team_id=self.team_id, id=kwargs["pk"]).delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


def valid_domain(url) -> bool:
    target_domain = urlparse(url).netloc
    return target_domain == "hooks.zapier.com"
