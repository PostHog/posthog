"""Personhog fake activation for tests.

activate_personhog_fake() patches get_personhog_client so all person/group reads
route through a FakePersonHogClient, and blocks ORM access to persons-DB models
for the duration of the test so nothing can silently fall back to the persons DB.

Test data is seeded into the fake (and ClickHouse) by the helpers in
posthog.test.persons — no Django signals or ORM writes are involved.
"""

from __future__ import annotations

from contextlib import contextmanager

from unittest.mock import patch

from posthog.person_db_router import block_persons_orm, unblock_persons_orm
from posthog.personhog_client.fake_client import FakePersonHogClient

_active_fake: FakePersonHogClient | None = None


def set_active_fake(fake: FakePersonHogClient | None) -> None:
    global _active_fake
    _active_fake = fake


def get_active_fake() -> FakePersonHogClient:
    assert _active_fake is not None, "get_active_fake() called outside activate_personhog_fake() context"
    return _active_fake


@contextmanager
def activate_personhog_fake():
    """Activate a FakePersonHogClient for the duration of a test.

    Patches get_personhog_client so all reads route through the fake and blocks
    persons-DB ORM access so a stray Person.objects.* call fails loudly.  Test
    helpers in posthog.test.persons seed the fake explicitly when creating data.
    """
    fake = FakePersonHogClient()
    set_active_fake(fake)
    block_persons_orm()
    with patch("posthog.personhog_client.client.get_personhog_client", return_value=fake):
        try:
            yield fake
        finally:
            unblock_persons_orm()
            set_active_fake(None)
