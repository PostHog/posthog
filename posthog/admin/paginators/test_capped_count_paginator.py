from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.admin.paginators.capped_count_paginator import CappedCountPaginator
from posthog.models import AsyncDeletion
from posthog.models.async_deletion import DeletionType


class TestCappedCountPaginator(BaseTest):
    @parameterized.expand([("below_cap", 2, 2, 1), ("above_cap", 5, 3, 2)])
    def test_count_stops_at_cap(self, _name: str, rows: int, expected_count: int, expected_pages: int) -> None:
        AsyncDeletion.objects.bulk_create(
            AsyncDeletion(team_id=self.team.id, deletion_type=DeletionType.Person, key=f"key-{i}") for i in range(rows)
        )
        with patch.object(CappedCountPaginator, "MAX_COUNT", 3):
            paginator = CappedCountPaginator(AsyncDeletion.objects.order_by("-id"), per_page=2)
            assert paginator.count == expected_count
            assert paginator.num_pages == expected_pages
            assert len(paginator.page(paginator.num_pages).object_list) > 0
