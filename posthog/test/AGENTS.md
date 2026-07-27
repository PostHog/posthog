# Test infrastructure for person, group, and cohort data

## The rule

**Never use `Person.objects.create()`, `Group.objects.create()`, `GroupTypeMapping.objects.create()`, or `CohortPeople.objects.create()` directly in tests.**

Use the centralized helpers in `posthog/test/persons.py` instead.
They seed the active personhog fake (and, for persons, ClickHouse) so reads through personhog see the data.
They do NOT write to the persons DB — personhog is the sole source of truth.

The persons DB router raises `PersonsDBORMBlockedError` on any ORM access to a persons-DB model while a
test's personhog fake is active, so a direct `Person.objects.create(...)` / `.get(...)` / `.filter(...)` in a
test fails loudly. Route writes through the helpers below and reads through the personhog helpers in
`posthog/models/person/util.py` (`get_person_by_uuid`, `get_persons_by_distinct_ids`, …).

## Quick reference

```python
from posthog.test.persons import (
    create_person,          # immediate: ClickHouse + fake
    delete_person,          # unseed fake
    add_distinct_id,        # add a distinct ID to an existing person
    update_person,          # re-sync mutated person to ClickHouse + fake
    create_group,
    update_group,
    create_group_type_mapping,
    update_group_type_mapping,
    add_cohort_members,
    remove_cohort_members,
)
```

### Creating a person

```python
# Immediate creation (writes to Postgres now, seeds fake)
person = create_person(team=self.team, distinct_ids=["user1"], properties={"email": "a@b.com"})

# team_id= also works
person = create_person(team_id=self.team.pk, distinct_ids=["user1"])

# Adding a distinct ID to an existing person
add_distinct_id(person=person, distinct_id="another_id", version=0)
```

### Deferred (batched) creation

The `_create_person()` → `flush_persons_and_events()` pattern from `BaseTest` still works.
Under the hood, `_create_person` calls `stage_person_for_bulk_create` which defers writes until `flush_persons_and_events()` bulk-inserts to Postgres + ClickHouse + seeds the fake.

Use this when you need persons and events synced to ClickHouse together.

### Groups and group type mappings

```python
create_group_type_mapping(team=self.team, group_type="organization", group_type_index=0)
create_group(team=self.team, group_type_index=0, group_key="org:5", group_properties={"industry": "tech"})
```

### Cohort members

```python
add_cohort_members(cohort=cohort, persons=[person1, person2])
remove_cohort_members(cohort=cohort, persons=[person1])
```

## Why this exists

PostHog moved person/group reads from the Django ORM to a gRPC service (personhog), which is now the
sole source of truth. In tests, a `FakePersonHogClient` stands in for the real service, and the persons
DB is not used at all — the router blocks ORM access to persons-DB models while the fake is active.
The helpers seed the fake (and ClickHouse for persons) so code under test reads consistent data.

Tests that exercise the persons DB _layer itself_ (the temporal `sync_person_distinct_ids` / `backfill_*`
activities, the dagster persons-maintenance jobs, and `test_person_schema`) are excluded from the fake
in the root `conftest.py` and keep direct persons-DB access.

## Other test utilities that create persons

- `posthog/test/test_journeys.py` → `journeys_for()` / `update_or_create_person()` — these already seed the fake internally
- `posthog/test/base.py` → `_create_person()` — thin wrapper around `stage_person_for_bulk_create`
- `posthog/test/test_utils.py` → `create_group_type_mapping_without_created_at()` — uses the helper internally

If you add a new utility that creates person/group data, it must seed the fake.
Import `_seed_person_into_fake` / `_seed_group_into_fake` / etc. from `posthog.test.persons`.
