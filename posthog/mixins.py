import copy
from datetime import datetime
from itertools import zip_longest
from typing import Any, Dict, Iterable, List, Tuple, Union

import structlog
from rest_framework import response, serializers, status

from posthog.event_usage import report_user_action
from posthog.helpers.item_history import compute_history
from posthog.models import HistoricalVersion

logger = structlog.get_logger(__name__)


# from https://stackoverflow.com/a/4628446/222163
def pairwise(t: List[HistoricalVersion]) -> Iterable[Tuple[HistoricalVersion, Union[HistoricalVersion, None]]]:
    left = iter(t)
    right = iter(t[1:])
    return zip_longest(left, right)


def _version_for_deletion(instance, item_id: int, team_id: int, metadata: Dict, user: Dict) -> None:
    """
    In order to maintain the behaviour of AnalyticsDestroyModelMixin we can't reverse the direction of dependency
    Which means we can't inject a serializer instance

    This means we don't always capture all object state on deletion.
    In most cases this will be fine and the previous HistoricalVersion will contain any state needed
    """
    state = as_deletion_state(metadata)

    version = HistoricalVersion(
        state=state,
        name=instance.__class__.__name__,
        action="delete",
        item_id=item_id,
        created_by_name=user["first_name"],
        created_by_email=user["email"],
        created_by_id=user["id"],
        team_id=team_id,
    )

    version.save()


def as_deletion_state(metadata: Dict) -> Dict:
    state = copy.deepcopy(metadata)
    if state["created_at"] and isinstance(state["created_at"], datetime):
        state["created_at"] = state["created_at"].isoformat()
    return state


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


def load_history(history_type: str, team_id: int, item_id: int, instance, serializer):
    """
     * loads a page of history for that type and id (newest first)
     * and returns a computed history for that page of history
    """

    # In order to make a page of up to 10 we need to get up to 11 as we need N-1 to determine what changed
    versions = list(
        HistoricalVersion.objects.filter(  # TODO handle items with org id not team id
            team_id=team_id, name=history_type, item_id=item_id
        ).order_by("-versioned_at")[:11]
    )

    if len(versions) == 0:
        """
        This item existed before history logging and this is the first time it's been viewed.
        Create an import and capture the state as it is now
        Otherwise the first change made by a user shows as a change to every field
        """
        imported_version = HistoricalVersion(
            state=serializer(instance).data,
            name="FeatureFlag",
            action="update",
            item_id=item_id,
            created_by_name="history hog",
            created_by_email="history.hog@posthog.com",
            created_by_id=0,
            team_id=team_id,
        )
        imported_version.save()

        versions.append(imported_version)

    return compute_history(history_type=history_type, version_pairs=(pairwise(versions)),)


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

    def destroy(self, request, *args, **kwargs):

        instance = self.get_object()  # type: ignore

        metadata = instance.get_analytics_metadata() if hasattr(instance, "get_analytics_metadata",) else {}

        instance.delete()

        report_user_action(request.user, f"{instance._meta.verbose_name} deleted", metadata)

        if _should_log_history(instance) and metadata:
            """
            This is mixed in to API view sets so has team_id available
            TODO handle models with organization id not team id
            """
            team_id = self.team_id  # type:ignore
            _version_for_deletion(
                instance=instance,
                item_id=kwargs["pk"],
                team_id=team_id,
                metadata=metadata,
                user={"first_name": request.user.first_name, "email": request.user.email, "id": request.user.id},
            )

        return response.Response(status=status.HTTP_204_NO_CONTENT)
