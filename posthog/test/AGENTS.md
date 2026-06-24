# Test infrastructure for person, group, and cohort data

## The rule

**Never use `Person.objects.create()`, `Group.objects.create()`, `GroupTypeMapping.objects.create()`, or `CohortPeople.objects.create()` directly in tests.**

Use the centralized helpers in `posthog/test/persons.py` instead.
They write to Postgres AND seed the active personhog fake so both read paths see the data.

Direct ORM calls skip the fake — tests will silently return empty results from any code path that reads through personhog.

## Quick reference

```python
from posthog.test.persons import (
    create_person,          # immediate: ORM + fake
    add_distinct_id,        # add a distinct ID to an existing person
    update_person,          # person.save() + re-seed fake
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

PostHog is migrating person/group reads from the Django ORM to a gRPC service (personhog).
In tests, a `FakePersonHogClient` stands in for the real service.
The helpers ensure both the ORM (for code that still reads from Postgres) and the fake (for code that reads through personhog) stay in sync.

When the ORM fallback is fully removed, the ORM writes in these helpers get deleted — one place to change, not 75+ test files.

## Other test utilities that create persons

- `posthog/test/test_journeys.py` → `journeys_for()` / `update_or_create_person()` — these already seed the fake internally
- `posthog/test/base.py` → `_create_person()` — thin wrapper around `stage_person_for_bulk_create`
- `posthog/test/test_utils.py` → `create_group_type_mapping_without_created_at()` — uses the helper internally

If you add a new utility that creates person/group data, it must seed the fake.
Import `_seed_person_into_fake` / `_seed_group_into_fake` / etc. from `posthog.test.persons` and call them after the ORM write.
