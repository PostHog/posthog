from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.utils import timezone

from ee.models.assistant import CoreMemory
import pytest


class TestCoreMemory(BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(team=self.team)

    async def test_status_changes(self):
        # Test pending status
        await self.core_memory.achange_status_to_pending()
        assert self.core_memory.scraping_status == CoreMemory.ScrapingStatus.PENDING
        assert self.core_memory.scraping_started_at is not None

        # Test skipped status
        await self.core_memory.achange_status_to_skipped()
        assert self.core_memory.scraping_status == CoreMemory.ScrapingStatus.SKIPPED

    async def test_scraping_status_properties(self):
        # Test pending status within time window
        await self.core_memory.achange_status_to_pending()
        assert self.core_memory.is_scraping_pending

        # Test pending status outside time window
        self.core_memory.scraping_started_at = timezone.now() - timedelta(minutes=11)
        await self.core_memory.asave()
        assert not self.core_memory.is_scraping_pending

        # Test finished status
        self.core_memory.scraping_status = CoreMemory.ScrapingStatus.COMPLETED
        await self.core_memory.asave()
        assert self.core_memory.is_scraping_finished

        self.core_memory.scraping_status = CoreMemory.ScrapingStatus.SKIPPED
        await self.core_memory.asave()
        assert self.core_memory.is_scraping_finished

    @freeze_time("2023-01-01 12:00:00")
    async def test_is_scraping_pending_timing(self):
        # Set initial pending status
        await self.core_memory.achange_status_to_pending()
        initial_time = timezone.now()

        # Test 3 minutes after (should be true)
        with freeze_time(initial_time + timedelta(minutes=3)):
            assert self.core_memory.is_scraping_pending

        # Test exactly 5 minutes after (should be false)
        with freeze_time(initial_time + timedelta(minutes=10)):
            assert not self.core_memory.is_scraping_pending

        # Test 6 minutes after (should be false)
        with freeze_time(initial_time + timedelta(minutes=11)):
            assert not self.core_memory.is_scraping_pending

    async def test_core_memory_operations(self):
        # Test setting core memory
        test_text = "Test memory content"
        await self.core_memory.aset_core_memory(test_text)
        assert self.core_memory.text == test_text
        assert self.core_memory.initial_text == ""
        assert self.core_memory.scraping_status == CoreMemory.ScrapingStatus.COMPLETED

        # Test appending core memory
        append_text = "Additional content"
        await self.core_memory.aappend_core_memory(append_text)
        assert self.core_memory.text == f"{test_text}\n{append_text}"

        # Test replacing core memory
        original = "content"
        new = "memory"
        await self.core_memory.areplace_core_memory(original, new)
        assert new in self.core_memory.text
        assert original not in self.core_memory.text

        # Test replacing non-existent content
        with pytest.raises(ValueError):
            await self.core_memory.areplace_core_memory("nonexistent", "new")

    async def test_formatted_text(self):
        # Test formatted text with short content
        short_text = "Short text"
        await self.core_memory.aset_core_memory(short_text)
        assert self.core_memory.formatted_text == short_text

        # Test formatted text with long content
        long_text = "x" * 6000
        await self.core_memory.aset_core_memory(long_text)
        assert len(self.core_memory.formatted_text) == 5001
        assert self.core_memory.formatted_text == long_text[:2500] + "…" + long_text[-2500:]
