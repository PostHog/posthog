from datetime import UTC, datetime

import pytest

from django.core.management.base import CommandError

from posthog.management.commands.resend_weekly_digest import period_end_for_digest_key


def test_period_end_for_digest_key_is_the_monday_of_the_iso_week():
    # ISO week 1 of 2026 starts in December 2025.
    assert period_end_for_digest_key("weekly-digest-2026-1") == datetime(2025, 12, 29, tzinfo=UTC)


@pytest.mark.parametrize("digest_key", ["weekly-digest-2026", "weekly-digest-2026-54"])
def test_period_end_for_digest_key_rejects_keys_it_cannot_date(digest_key):
    with pytest.raises(CommandError):
        period_end_for_digest_key(digest_key)
