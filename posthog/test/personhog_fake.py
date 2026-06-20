"""Test-only wiring that routes person reads through the in-memory personhog fake.

Production removed the ORM fallback from person data access, so person reads now
go through personhog or raise. In the test suite we activate ``FakePersonHogClient``
globally (see ``PostHogTestCase``) and mirror persons created via the standard test
helpers into it.

This is a thin write-mirror of the test DB into the fake — every person written by
a test is copied into the fake so subsequent reads resolve. It does NOT reimplement
the personhog backend; the fake's own read logic is used unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models import Person, PersonDistinctId

if TYPE_CHECKING:
    from posthog.personhog_client.fake_client import FakePersonHogClient

# The fake activated by the currently-running test (set in ``PostHogTestCase.setUp``).
# ``None`` outside a test, which makes the signal mirrors below no-ops.
_active_fake: FakePersonHogClient | None = None


def set_active_fake(fake: FakePersonHogClient | None) -> None:
    global _active_fake
    _active_fake = fake


def _created_at_ms(person: Person) -> int:
    return int(person.created_at.timestamp() * 1000) if person.created_at else 0


def _seed_person(fake: FakePersonHogClient, person: Person, distinct_ids: list[str]) -> None:
    fake.add_person(
        team_id=person.team_id,
        person_id=person.pk,
        uuid=str(person.uuid),
        properties=person.properties or {},
        is_identified=person.is_identified,
        created_at=_created_at_ms(person),
        distinct_ids=distinct_ids,
    )


def seed_persons_from_mapping(person_mapping: dict[str, Person]) -> None:
    """Seed the active fake from a ``{distinct_id: Person}`` mapping.

    Used by ``flush_persons_and_events`` to cover the ``bulk_create`` path, which
    bypasses Django signals and so isn't caught by the mirrors below.
    """
    fake = _active_fake
    if fake is None or not person_mapping:
        return
    by_person: dict[int, tuple[Person, list[str]]] = {}
    for distinct_id, person in person_mapping.items():
        _, distinct_ids = by_person.setdefault(person.pk, (person, []))
        distinct_ids.append(distinct_id)
    for person, distinct_ids in by_person.values():
        _seed_person(fake, person, distinct_ids)


@receiver(post_save, sender=Person)
def _mirror_person(sender: type[Person], instance: Person, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    _seed_person(fake, instance, [])


@receiver(post_save, sender=PersonDistinctId)
def _mirror_distinct_id(sender: type[PersonDistinctId], instance: PersonDistinctId, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    _seed_person(fake, instance.person, [instance.distinct_id])
