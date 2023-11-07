from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, List, Tuple

import structlog
from django.utils import timezone

from posthog.models.async_deletion import AsyncDeletion, DeletionType

logger = structlog.get_logger(__name__)


class AsyncDeletionProcess(ABC):
    CLICKHOUSE_CHUNK_SIZE = 1000
    DELETION_TYPES: List[DeletionType] = []

    def __init__(self) -> None:
        super().__init__()

    def run(self):
        queued_deletions = list(
            AsyncDeletion.objects.filter(delete_verified_at__isnull=True, deletion_type__in=self.DELETION_TYPES)
        )
        for i in range(0, len(queued_deletions), self.CLICKHOUSE_CHUNK_SIZE):
            chunk = queued_deletions[i : i + self.CLICKHOUSE_CHUNK_SIZE]
            self.process(chunk)

    def mark_deletions_done(self):
        """
        Checks and updates `delete_verified_at` for deletions
        """
        to_verify = []
        unverified = self._fetch_unverified_deletions_grouped()

        for (deletion_type, _), async_deletions in unverified.items():
            for i in range(0, len(async_deletions), self.CLICKHOUSE_CHUNK_SIZE):
                chunk = async_deletions[i : i + self.CLICKHOUSE_CHUNK_SIZE]
                to_verify.extend(self._verify_by_group(deletion_type, chunk))

        if len(to_verify) > 0:
            AsyncDeletion.objects.filter(pk__in=[row.pk for row in to_verify]).update(delete_verified_at=timezone.now())
            logger.warn(
                "Updated `delete_verified_at` for AsyncDeletion",
                {
                    "count": len(to_verify),
                    "team_ids": list(set(row.team_id for row in to_verify)),
                },
            )

    def _fetch_unverified_deletions_grouped(self):
        result = defaultdict(list)
        items = AsyncDeletion.objects.filter(delete_verified_at__isnull=True, deletion_type__in=self.DELETION_TYPES)
        for item in items:
            key = (
                item.deletion_type,
                item.group_type_index,
            )  # group_type_index only relevant for "group" deletion type
            result[key].append(item)
        return result

    @abstractmethod
    def process(self, deletions: List[AsyncDeletion]):
        raise NotImplementedError()

    @abstractmethod
    def _verify_by_group(self, deletion_type: int, async_deletions: List[AsyncDeletion]) -> List[AsyncDeletion]:
        raise NotImplementedError()

    def _conditions(self, async_deletions: List[AsyncDeletion]) -> Tuple[List[str], Dict]:
        conditions, args = [], {}
        for i, row in enumerate(async_deletions):
            condition, arg = self._condition(row, str(i))
            conditions.append(condition)
            args.update(arg)
        return conditions, args

    @abstractmethod
    def _condition(self, async_deletion: AsyncDeletion, suffix: str) -> Tuple[str, Dict]:
        raise NotImplementedError()
