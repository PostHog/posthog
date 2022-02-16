import dataclasses
from typing import Dict, Iterable, List, Optional, Tuple, Union

from posthog.models import HistoricalVersion


@dataclasses.dataclass(frozen=True)
class HistoryListItem:
    email: Optional[str]
    name: Optional[str]
    user_id: int
    action: str
    detail: Dict[str, Union[int, str, Dict]]
    created_at: str


def compute_history(
    history_type: str, version_pairs: Iterable[Tuple[HistoricalVersion, Optional[HistoricalVersion]]],
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

    for (current, previous) in version_pairs:
        if current.action == "create":
            history.append(
                HistoryListItem(
                    email=current.created_by_email,
                    name=current.created_by_name,
                    user_id=current.created_by_id,
                    action=f"{history_type}_created",
                    detail={"id": current.item_id, "key": current.state["key"]},
                    created_at=current.versioned_at.isoformat(),
                )
            )
        elif current.action == "delete":
            history.append(
                HistoryListItem(
                    email=current.created_by_email,
                    name=current.created_by_name,
                    user_id=current.created_by_id,
                    action=f"{history_type}_deleted",
                    detail={"id": current.item_id, "key": current.state["key"]},
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
                            action=f"{history_type}_{current_key}_changed",
                            detail={
                                "id": current.item_id,
                                "key": current.state["key"],
                                "to": current.state[current_key],
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
                            action=f"{history_type}_{current_key}_changed",
                            detail={
                                "id": current.item_id,
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
                            action=f"{history_type}_{previous_key}_deleted",
                            detail={
                                "id": current.item_id,
                                "key": current.state["key"],
                                "deleted": previous.state[previous_key],
                            },
                            created_at=current.versioned_at.isoformat(),
                        )
                    )
        elif previous is None and current.action != "create":
            history.append(
                HistoryListItem(
                    email="history.hog@posthog.com",
                    name="history hog",
                    user_id=-1,
                    action=f"{history_type}_imported",
                    detail={"id": current.item_id, "key": current.state["key"]},
                    created_at=current.versioned_at.isoformat(),
                )
            )

    return history
