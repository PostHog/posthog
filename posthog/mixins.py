import json
from itertools import zip_longest
from typing import Any, Iterable, List, Optional, Tuple, Union

import structlog
from django.core import serializers as django_serilizers
from rest_framework import request, response, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.event_usage import report_user_action
from posthog.helpers.item_history import compute_history
from posthog.models import HistoricalVersion

logger = structlog.get_logger(__name__)


# from https://stackoverflow.com/a/4628446/222163
def pairwise(t: List[HistoricalVersion]) -> Iterable[Tuple[HistoricalVersion, Union[HistoricalVersion, None]]]:
    left = iter(t)
    right = iter(t[1:])
    return zip_longest(left, right)


def _version_from_request(instance, state: str, request, action: str) -> None:
    instance_state = json.loads(state)
    id = instance_state["pk"]  # because deleted instances have no primary key

    version = HistoricalVersion(
        state=state,
        name=instance.__class__.__name__,
        action=action,
        item_id=id,
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
        item_id=serializer.instance.id,
        action=action,
        created_by_name=serializer.context["request"].user.first_name,
        created_by_email=serializer.context["request"].user.email,
        created_by_id=serializer.context["request"].user.id,
        team_id=serializer.context["team_id"],
    ).save()


class HistoryListItemSerializer(serializers.Serializer):
    email = serializers.EmailField(read_only=True)
    name = serializers.CharField(read_only=True)
    user_id = serializers.IntegerField(read_only=True)
    action = serializers.CharField(read_only=True)
    detail = serializers.DictField(read_only=True)
    created_at = serializers.CharField(read_only=True)


def _should_log_history(instance: Any) -> bool:
    return instance.__class__.__name__ in ["FeatureFlag"]


class HistoryLoggingMixin:
    def perform_create(self, serializer):
        serializer.save()
        _version_from_serializer(serializer, "create")

    def perform_update(self, serializer):
        serializer.save()
        _version_from_serializer(serializer, "update")

    @action(methods=["GET"], detail=True)
    def history(self, request: request.Request, **kwargs):
        """
        Because we're inside a mixin being applied to a viewset
        we can add a history endpoint here to avoid cluttering up the viewset with history code

        so `self` here is the viewset

        this
         * uses the viewset's object to determine what type it is operating on,
         * loads a page of history for that type and id (newest first)
         * and returns a computed history for that page of history
        """
        history_type = self.get_object().__class__.__name__  # type: ignore
        # in order to make a page of up to 10 we need to get up to 11 as we need N-1 to determine what changed
        versions = HistoricalVersion.objects.filter(
            team_id=self.team.id, name=history_type, item_id=kwargs["pk"]  # type: ignore
        ).order_by("-versioned_at")[:11]

        return Response(
            {
                "results": HistoryListItemSerializer(
                    compute_history(  # TODO handle items with org id not team id
                        history_type=history_type,
                        version_pairs=pairwise(list(versions)),
                        item_id=kwargs["pk"],
                        team_id=self.team.id,  # type: ignore
                    ),
                    many=True,
                ).data,
                "next": None,
                "previous": None,
            },
            status=status.HTTP_200_OK,
        )


class AnalyticsDestroyModelMixin:
    """
    DestroyModelMixin enhancement that provides reporting of when an object is deleted.

    Generally this would be better off executed at the serializer level,
    but deletion (i.e. `destroy`) is performed directly in the viewset, which is why this mixin is a thing.
    """

    def destroy(self, request, *args, **kwgars):

        instance = self.get_object()  # type: ignore

        metadata = instance.get_analytics_metadata() if hasattr(instance, "get_analytics_metadata",) else {}

        state: Optional[str] = None
        if _should_log_history(instance):
            # ¯\_(ツ)_/¯ serialize the instance as a list and then chop off the square braces
            # TRICKY serializing the instance here isn't straightforward
            # approach taken from https://stackoverflow.com/a/2391243
            state = django_serilizers.serialize("json", [instance])[1:-1]

        instance.delete()

        report_user_action(request.user, f"{instance._meta.verbose_name} deleted", metadata)

        if _should_log_history(instance) and state:
            _version_from_request(instance, state, request, "delete")

        return response.Response(status=status.HTTP_204_NO_CONTENT)
