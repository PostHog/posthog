import structlog
from django.core import serializers
from rest_framework import response, status

from posthog.event_usage import report_user_action
from posthog.models import HistoricalVersion

logger = structlog.get_logger(__name__)


def _version_from_request(instance, state: str, request, action: str) -> None:
    version = HistoricalVersion(
        state=state,
        name=instance.__class__.__name__,
        action=action,
        created_by_name=request.user.first_name,
        created_by_email=request.user.email,
        created_by_id=request.user.id,
    )

    if hasattr(instance, "team_id"):
        version.team_id = instance.team_id

    version.save()


def _version_from_serializer(serializer, action: str) -> None:
    HistoricalVersion(
        state=serializer.data,
        name=serializer.instance.__class__.__name__,
        action=action,
        created_by_name=serializer.context["request"].user.first_name,
        created_by_email=serializer.context["request"].user.email,
        created_by_id=serializer.context["request"].user.id,
        team_id=serializer.context["team_id"],
    ).save()


class HistoryLoggingMixin:
    def perform_create(self, serializer):
        serializer.save()
        _version_from_serializer(serializer, "create")

    def perform_update(self, serializer):
        serializer.save()
        _version_from_serializer(serializer, "update")


class AnalyticsDestroyModelMixin:
    """
    DestroyModelMixin enhancement that provides reporting of when an object is deleted.

    Generally this would be better off executed at the serializer level,
    but deletion (i.e. `destroy`) is performed directly in the viewset, which is why this mixin is a thing.
    """

    def destroy(self, request, *args, **kwgars):

        instance = self.get_object()  # type: ignore

        metadata = instance.get_analytics_metadata() if hasattr(instance, "get_analytics_metadata",) else {}

        # ¯\_(ツ)_/¯ serialize the instance as a list and then chop off th
        # TRICKY serializing the instance here isn't straightforward
        # approach taken from https://stackoverflow.com/a/2391243e square braces
        state: str = serializers.serialize("json", [instance])[1:-1]

        instance.delete()

        report_user_action(request.user, f"{instance._meta.verbose_name} deleted", metadata)

        _version_from_request(instance, state, request, "delete")

        return response.Response(status=status.HTTP_204_NO_CONTENT)
