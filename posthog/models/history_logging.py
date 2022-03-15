import dataclasses
from itertools import zip_longest
from typing import Dict, Iterable, List, Literal, Optional, Tuple, Union

from rest_framework import serializers

import posthog.models
from posthog.models import HistoricalVersion, User


class ChangeSerializer(serializers.Serializer):
    type = serializers.CharField(read_only=True)
    key = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)
    detail = serializers.DictField(read_only=True)


class HistoryListItemSerializer(serializers.Serializer):
    email = serializers.EmailField(read_only=True)
    name = serializers.CharField(read_only=True)
    user_id = serializers.IntegerField(read_only=True)
    changes = ChangeSerializer(many=True)
    created_at = serializers.CharField(read_only=True)


@dataclasses.dataclass(frozen=True)
class Change:
    type: Literal["FeatureFlag"]
    key: Optional[str]
    action: Literal["imported", "changed", "created", "deleted"]
    detail: Dict[str, Union[int, str, Dict]]


@dataclasses.dataclass(frozen=True)
class HistoryListItem:
    email: Optional[str]
    name: Optional[str]
    changes: List[Change]
    created_at: str


# from https://stackoverflow.com/a/4628446/222163
def pairwise(
    historical_versions: List[HistoricalVersion],
) -> Iterable[Tuple[HistoricalVersion, Union[HistoricalVersion, None]]]:
    left = iter(historical_versions)
    right = iter(historical_versions[1:])
    return zip_longest(left, right)


def load_history(history_type: Literal["FeatureFlag"], team_id: int, item_id: int, instance, serializer):
    """
     * loads a page of history for that type and id (newest first)
     * and returns a computed history for that page of history
    """

    # In order to make a page of up to 10 we need to get up to 11 as we need N-1 to determine what changed
    versions = list(
        HistoricalVersion.objects.filter(team_id=team_id, name=history_type, item_id=item_id).order_by("-versioned_at")[
            :11
        ]
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
            created_by=_get_history_hog(),
            team_id=team_id,
        )
        imported_version.save()

        versions.append(imported_version)

    return compute_history(history_type=history_type, version_pairs=(pairwise(versions)),)


def _get_history_hog() -> posthog.models.User:
    """
    For models created before history logging began we don't know who created them or last updated them.

    Instead of displaying them as "unknown user" we'll say "History Hog" has imported them
    """
    return User.objects.get_or_create(first_name="history hog", email="history.hog@posthog.com")[0]


def compute_history(
    history_type: Literal["FeatureFlag"],
    version_pairs: Iterable[Tuple[HistoricalVersion, Optional[HistoricalVersion]]],
):
    """
    TODO Purposefully leaving this as unstructured "Arrow code" to get to "shameless green"
    TODO until there are at least two or three types having history computed
    TODO to avoid premature abstraction

    takes a type of item e.g. FeatureFlag or Insight
    and a set of version pairs
    and uses them to compute a history for that instance of that type

    The version pairs are an overlapping zip of the item's history
    So if its history is [a, b, c, d] this function receives [(a, b), (b, c), (c, d), (d, None)]
    (where a is the most recent recorded change)
    It uses the right-hand side of each tuple to determine what changed to generate the left-hand side
    """
    history: List[HistoryListItem] = []

    for pair in version_pairs:
        current: HistoricalVersion
        previous: Optional[HistoricalVersion]
        (current, previous) = pair

        changes: List[Change] = []

        if current.action == "create":
            changes.append(
                Change(
                    type=history_type,
                    key=None,
                    action="created",
                    detail={"id": current.item_id, "key": current.state["key"]},
                )
            )
        elif current.action == "delete":
            changes.append(
                Change(
                    type=history_type,
                    key=None,
                    action="deleted",
                    detail={"id": current.item_id, "key": current.state["key"]},
                )
            )
        elif current.action == "update" and previous is not None:
            for current_key in current.state:
                if current_key not in previous.state:
                    changes.append(
                        Change(
                            type=history_type,
                            key=current_key,
                            action="changed",
                            detail={
                                "id": current.item_id,
                                "key": current.state["key"],
                                "to": current.state[current_key],
                            },
                        )
                    )
                elif current.state[current_key] != previous.state[current_key]:
                    changes.append(
                        Change(
                            type=history_type,
                            key=current_key,
                            action="changed",
                            detail={
                                "id": current.item_id,
                                "key": current.state["key"],
                                "from": previous.state[current_key],
                                "to": current.state[current_key],
                            },
                        )
                    )

            for previous_key in previous.state:
                if previous_key not in current.state:
                    changes.append(
                        Change(
                            type=history_type,
                            key=previous_key,
                            action="deleted",
                            detail={
                                "id": current.item_id,
                                "key": current.state["key"],
                                "deleted": previous.state[previous_key],
                            },
                        )
                    )
        elif previous is None and current.action != "create":
            changes.append(
                Change(
                    type=history_type,
                    key=None,
                    action="imported",
                    detail={"id": current.item_id, "key": current.state["key"]},
                )
            )

        history.append(
            HistoryListItem(
                email=_safely_read_email(current),
                name=_safely_read_first_name(current),
                created_at=current.versioned_at.isoformat(),
                changes=changes,
            )
        )

    return history


def _safely_read_email(version: Optional[HistoricalVersion]) -> Optional[str]:
    if version and version.created_by:
        return version.created_by.email

    return None


def _safely_read_first_name(version: Optional[HistoricalVersion]) -> str:
    if version and version.created_by:
        return version.created_by.first_name

    return "unknown user"
