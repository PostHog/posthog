import dataclasses
from enum import Enum
from itertools import zip_longest
from typing import Dict, Iterable, List, Optional, Tuple, Union

import structlog
from django.core import serializers
from rest_framework import request, response, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.event_usage import report_user_action
from posthog.models import HistoricalVersion

logger = structlog.get_logger(__name__)


# from https://stackoverflow.com/a/4628446/222163
def pairwise(t):
    it = iter(t)
    return zip_longest(it, it)


def _version_from_request(instance, state: str, request, action: str) -> None:
    version = HistoricalVersion(
        state=state,
        name=instance.__class__.__name__,
        action=action,
        item_id=instance.id,
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


@dataclasses.dataclass(frozen=True)
class HistoryListItem:
    email: Optional[str]
    name: Optional[str]
    user_id: int
    action: str
    detail: Dict[str, Union[int, str]]
    created_at: str


def compute_history(history_type: str, version_pairs: Iterable[Tuple[HistoricalVersion, HistoricalVersion]]):
    history: List[HistoryListItem] = []

    for (current, previous) in version_pairs:
        if current.action == "create":
            history.append(
                HistoryListItem(
                    email=current.created_by_email,
                    name=current.created_by_name,
                    user_id=current.created_by_id,
                    action=f"created_{history_type}",
                    detail={"id": current.state["id"], "key": current.state["key"]},
                    created_at=current.versioned_at.isoformat(),
                )
            )
        elif current.action == "delete":
            history.append(
                HistoryListItem(
                    email=current.created_by_email,
                    name=current.created_by_name,
                    user_id=current.created_by_id,
                    action=f"deleted_{history_type}",
                    detail={"id": current.state["id"], "key": current.state["key"]},
                    created_at=current.versioned_at.isoformat(),
                )
            )
        elif current.action == "update" and previous is not None:
            for current_key in current.state:
                if current_key not in previous.state:
                    history.append(
                        HistoryListItem(
                            email=current.created_by_email,
                            name=current.created_by_name,
                            user_id=current.created_by_id,
                            action=f"added_{current_key}_to_{history_type}",
                            detail={
                                "id": current.state["id"],
                                "key": current.state["key"],
                                "added": current.state[current_key],
                            },
                            created_at=current.versioned_at.isoformat(),
                        )
                    )
                elif current.state[current_key] != previous.state[current_key]:
                    history.append(
                        HistoryListItem(
                            email=current.created_by_email,
                            name=current.created_by_name,
                            user_id=current.created_by_id,
                            action=f"changed_{current_key}",
                            detail={
                                "id": current.state["id"],
                                "key": current.state["key"],
                                "from": previous.state[current_key],
                                "to": current.state[current_key],
                            },
                            created_at=current.versioned_at.isoformat(),
                        )
                    )

            for previous_key in previous.state:
                if previous_key not in current.state:
                    history.append(
                        HistoryListItem(
                            email=current.created_by_email,
                            name=current.created_by_name,
                            user_id=current.created_by_id,
                            action=f"deleted_{previous_key}_from_{history_type}",
                            detail={
                                "id": current.state["id"],
                                "key": current.state["key"],
                                "deleted": previous.state[previous_key],
                            },
                            created_at=current.versioned_at.isoformat(),
                        )
                    )

    return history


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
        Because we're inside a mixin being appled to a viewset
        we can add a history endpoint here to avoid cluttering up the viewset with history code

        so `self` here is the viewset
        """
        # determine type of history
        history_type = self.get_object().__class__.__name__
        # lookup history
        # in order to make a page of up to 10 we need to get up to 11 as we need N-1 to determine what changed
        versions = HistoricalVersion.objects.filter(
            team_id=kwargs["parent_lookup_team_id"], name=history_type, item_id=kwargs["pk"]
        ).order_by("versioned_at")[:11]

        return Response(
            HistoryListItemSerializer(compute_history(history_type, pairwise(versions)), many=True).data,
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

        # ¯\_(ツ)_/¯ serialize the instance as a list and then chop off th
        # TRICKY serializing the instance here isn't straightforward
        # approach taken from https://stackoverflow.com/a/2391243e square braces
        state: str = serializers.serialize("json", [instance])[1:-1]

        instance.delete()

        report_user_action(request.user, f"{instance._meta.verbose_name} deleted", metadata)

        _version_from_request(instance, state, request, "delete")

        return response.Response(status=status.HTTP_204_NO_CONTENT)
