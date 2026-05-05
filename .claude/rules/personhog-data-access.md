---
paths:
  - 'posthog/models/person/**'
  - 'posthog/models/cohort/**'
  - 'posthog/models/group_type_mapping.py'
  - 'posthog/personhog_client/**'
  - 'posthog/api/person*.py'
  - 'posthog/api/cohort*.py'
  - 'posthog/queries/**'
  - 'posthog/management/commands/**'
  - 'products/*/backend/**/*.py'
  - 'ee/**/*.py'
---

# Person/group data access — use personhog client

Use the personhog client for all person/group data access — do not query persons DB tables via the
Django ORM or raw SQL. The `posthog/personhog_client/` gRPC client is the required interface for
reading and writing person-related data.

This applies to the following tables:
`posthog_person`, `posthog_persondistinctid`, `posthog_cohortpeople`, `posthog_group`,
`posthog_grouptypemapping`, and related override tables (`posthog_personoverride`,
`posthog_pendingpersonoverride`, `posthog_flatpersonoverride`, `posthog_featureflaghashkeyoverride`,
`posthog_personlessdistinctid`, `posthog_personoverridemapping`).

Use the helpers in `posthog/models/person/util.py` (e.g. `get_person_by_uuid`,
`get_persons_by_distinct_ids`, `get_person_by_distinct_id`) and `posthog/models/group_type_mapping.py`
(`get_group_types_for_project`) — these already route through personhog with ORM fallback via
`_personhog_routed()`.

When adding new person/group data access, follow the same `_personhog_routed()` pattern: provide a
`personhog_fn` using `get_personhog_client()` and an `orm_fn` fallback. Never add new direct ORM
queries like `Person.objects.filter(...)` or `PersonDistinctId.objects.filter(...)` — use the
existing routed helpers or create new ones following the established pattern.

See `posthog/personhog_client/README.md` for client details and `posthog/personhog_client/client.py`
for the full RPC interface.
