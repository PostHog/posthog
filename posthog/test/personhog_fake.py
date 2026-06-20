"""Test-only wiring that routes person/group reads through the in-memory personhog fake.

Production removed the ORM fallback from person and group data access, so those reads
now go through personhog or raise. In the test suite we activate ``FakePersonHogClient``
globally (see the autouse fixture in the root ``conftest.py``) and mirror rows created
via the ORM into it, so subsequent reads resolve.

This is a thin write-mirror of the test DB into the fake — every person / group /
group-type-mapping written by a test is copied into the fake. It does NOT reimplement
the personhog backend; the fake's own read logic is used unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models import Group, GroupTypeMapping, Person, PersonDistinctId
from posthog.personhog_client.fake_client import fake_personhog_client

if TYPE_CHECKING:
    from collections.abc import Iterator

    from posthog.personhog_client.fake_client import FakePersonHogClient

# The fake activated by the currently-running test (set by ``activate_personhog_fake``).
# ``None`` outside a test, which makes the signal mirrors below no-ops.
_active_fake: FakePersonHogClient | None = None


def set_active_fake(fake: FakePersonHogClient | None) -> None:
    global _active_fake
    _active_fake = fake


@contextmanager
def activate_personhog_fake() -> Iterator[FakePersonHogClient]:
    """Activate the personhog fake for the duration of a test.

    Patches ``get_personhog_client`` / the gate to the fake and registers it as the
    mirror target so ORM writes during the test are copied into it.
    """
    with fake_personhog_client() as fake:
        set_active_fake(fake)
        try:
            yield fake
        finally:
            set_active_fake(None)


def _created_at_ms(value: object) -> int:
    return int(value.timestamp() * 1000) if value else 0  # type: ignore[attr-defined]


def _seed_person(fake: FakePersonHogClient, person: Person, distinct_ids: list[str]) -> None:
    # Idempotent: ``add_person`` overwrites the person record but appends distinct ids,
    # so only hand it the ids the fake hasn't already mirrored for this person.
    key = (person.team_id, person.pk)
    existing = {d.distinct_id for d in fake._distinct_ids.get(key, [])}
    new_distinct_ids = [d for d in distinct_ids if d not in existing]
    fake.add_person(
        team_id=person.team_id,
        person_id=person.pk,
        uuid=str(person.uuid),
        properties=person.properties or {},
        is_identified=person.is_identified,
        created_at=_created_at_ms(person.created_at),
        distinct_ids=new_distinct_ids,
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


def _seed_group_type_mapping(fake: FakePersonHogClient, mapping: GroupTypeMapping) -> None:
    # Idempotent: the fake stores mappings in per-project / per-team lists, so drop any
    # existing entry for this index before re-adding.
    for store, store_key in (
        (fake._group_type_mappings_by_project, mapping.project_id),
        (fake._group_type_mappings_by_team, mapping.team_id),
    ):
        existing = store.get(store_key)
        if existing:
            store[store_key] = [m for m in existing if m.group_type_index != mapping.group_type_index]
    fake.add_group_type_mapping(
        project_id=mapping.project_id,
        team_id=mapping.team_id,
        group_type=mapping.group_type,
        group_type_index=mapping.group_type_index,
        id=mapping.pk or 0,
        name_singular=mapping.name_singular or "",
        name_plural=mapping.name_plural or "",
    )


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


@receiver(post_save, sender=Group)
def _mirror_group(sender: type[Group], instance: Group, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    fake.add_group(
        team_id=instance.team_id,
        group_type_index=instance.group_type_index,
        group_key=instance.group_key,
        group_properties=instance.group_properties or {},
        id=instance.pk or 0,
        created_at=_created_at_ms(instance.created_at),
        version=instance.version or 0,
    )


@receiver(post_save, sender=GroupTypeMapping)
def _mirror_group_type_mapping(sender: type[GroupTypeMapping], instance: GroupTypeMapping, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    _seed_group_type_mapping(fake, instance)
