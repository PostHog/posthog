from datetime import UTC, datetime

import pytest

from django.core.management.base import CommandError

from posthog.management.commands.resend_weekly_digest import period_end_for_digest_key


@pytest.mark.parametrize(
    "digest_key,expected",
    [
        ("weekly-digest-2026-45", datetime(2026, 11, 2, tzinfo=UTC)),
        # ISO week 1 of 2026 starts in December 2025.
        ("weekly-digest-2026-1", datetime(2025, 12, 29, tzinfo=UTC)),
    ],
)
def test_period_end_for_digest_key_is_the_monday_of_the_iso_week(digest_key, expected):
    assert period_end_for_digest_key(digest_key) == expected


@pytest.mark.parametrize("digest_key", ["weekly-digest-2026", "weekly-digest-2026-54", "my-custom-key"])
def test_period_end_for_digest_key_rejects_keys_it_cannot_date(digest_key):
    with pytest.raises(CommandError):
        period_end_for_digest_key(digest_key)
