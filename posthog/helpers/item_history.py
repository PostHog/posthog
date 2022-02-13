import dataclasses
from typing import Dict, Iterable, List, Optional, Tuple, Union

from posthog.models import HistoricalVersion


@dataclasses.dataclass(frozen=True)
class HistoryListItem:
    email: Optional[str]
    name: Optional[str]
    user_id: int
    action: str
    detail: Dict[str, Union[int, str]]
    created_at: str


def compute_history(history_type: str, version_pairs: Iterable[Tuple[HistoricalVersion, Optional[HistoricalVersion]]]):
    history: List[HistoryListItem] = []

    for (current, previous) in version_pairs:
        if current.action == "create":
            history.append(
                HistoryListItem(
                    email=current.created_by_email,
                    name=current.created_by_name,
                    user_id=current.created_by_id,
                    action=f"created_{history_type}",
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
                    action=f"deleted_{history_type}",
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
                            action=f"added_{current_key}_to_{history_type}",
                            detail={
                                "id": current.item_id,
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
                            action=f"changed_{current_key}_on_{history_type}",
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
                            action=f"deleted_{previous_key}_from_{history_type}",
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
                    action=f"history_hog_imported_{history_type}",
                    detail={"id": current.item_id, "key": current.state["key"]},
                    created_at=current.versioned_at.isoformat(),
                )
            )

    return history
