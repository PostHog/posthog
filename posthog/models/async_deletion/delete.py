from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, List, Tuple

import structlog
from django.utils import timezone

from posthog.models.async_deletion import AsyncDeletion

logger = structlog.get_logger(__name__)


class AsyncDeletionProcess(ABC):
    def __init__(self) -> None:
        super().__init__()

    def run(self):
        queued_deletions = list(AsyncDeletion.objects.filter(delete_verified_at__isnull=True))
        self.process(queued_deletions)

    def mark_deletions_done(self):
        """
        Checks and updates `delete_verified_at` for deletions
        """
        to_verify = []
        unverified = self._fetch_unverified_deletions_grouped()

        for (deletion_type, _), async_deletions in unverified.items():
            to_verify.extend(self._verify_by_group(deletion_type, async_deletions))

        if len(to_verify) > 0:
            AsyncDeletion.objects.filter(pk__in=[row.pk for row in to_verify]).update(delete_verified_at=timezone.now())
            logger.info(
                "Updated `delete_verified_at` for AsyncDeletion",
                {"count": len(to_verify), "team_ids": list(set(row.team_id for row in to_verify))},
            )

    def _fetch_unverified_deletions_grouped(self):
        result = defaultdict(list)
        for item in AsyncDeletion.objects.filter(delete_verified_at__isnull=True):
            key = (item.deletion_type, item.group_type_index)
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
