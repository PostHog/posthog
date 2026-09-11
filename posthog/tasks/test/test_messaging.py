from datetime import timedelta

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from posthog.models.messaging import MESSAGING_RECORD_RETENTION_DAYS, MessagingRecord
from posthog.tasks.messaging import cleanup_old_messaging_records

WINDOW = timedelta(days=MESSAGING_RECORD_RETENTION_DAYS)


class TestMessagingRecordCleanup(TestCase):
    def _record(self, campaign_key: str, age: timedelta) -> MessagingRecord:
        record = MessagingRecord.objects.create(email_hash=campaign_key, campaign_key=campaign_key)
        MessagingRecord.objects.filter(pk=record.pk).update(created_at=timezone.now() - age)
        return record

    def test_deletes_only_records_past_the_retention_window(self) -> None:
        self._record("expired", WINDOW + timedelta(days=1))
        inside_window = self._record("inside_window", WINDOW - timedelta(days=1))
        fresh = self._record("fresh", timedelta(0))

        cleanup_old_messaging_records()

        assert set(MessagingRecord.objects.values_list("pk", flat=True)) == {inside_window.pk, fresh.pk}

    @patch("posthog.tasks.messaging.CLEANUP_MAX_ROWS_PER_RUN", 2)
    @patch("posthog.tasks.messaging.CLEANUP_BATCH_SIZE", 1)
    def test_stops_at_the_per_run_cap(self) -> None:
        for index in range(3):
            self._record(f"expired_{index}", WINDOW + timedelta(days=1))

        cleanup_old_messaging_records()

        assert MessagingRecord.objects.count() == 1
