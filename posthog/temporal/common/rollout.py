from __future__ import annotations

import math
import hashlib
from typing import TypeVar

T = TypeVar("T")


def _rollout_rank(value: object) -> int:
    digest = hashlib.sha256(str(value).encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big")


def filter_ids_for_rollout(ids: list[T], rollout_percentage: float) -> list[T]:
    """Same `ids` + same percentage always yields the same subset, so canaries are stable across runs."""
    if rollout_percentage <= 0 or rollout_percentage > 1:
        raise ValueError(f"rollout_percentage must be in (0, 1], got {rollout_percentage}")
    if not ids:
        return []
    if rollout_percentage >= 1.0:
        return ids

    target_count = max(1, math.ceil(len(ids) * rollout_percentage))
    ranked = sorted(ids, key=lambda x: (_rollout_rank(x), str(x)))
    return ranked[:target_count]
