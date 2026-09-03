# Person data access: personhog vs ClickHouse

Django has two ways to read person information, and they are not interchangeable.
This doc says which source to use for what, and why.
It applies to all new code; some existing paths predate these rules and are noted as legacy below.

## The rules

**Use the personhog API for identity questions only:**

- Resolving distinct IDs to persons (`get_person_by_distinct_id`, `get_persons_by_distinct_ids`).
- Point lookups of a single person, or a small known set, by id or UUID (`get_person_by_uuid`, `get_person_by_id`, `validate_person_uuids_exist`).
- Person lifecycle writes: deletes, splits, cohort membership, hash key overrides.

**Use ClickHouse for everything property-shaped or bulk-shaped:**

- Loading person properties, whether for one person or many.
- Bulk lookups: hydrating a list of persons for display or export.
- Searching, filtering, and sorting persons (by property, cohort, or anything else).

The ClickHouse entry points are HogQL queries over the `persons` table and `ActorsQueryRunner` (`posthog/hogql_queries/actors_query_runner.py`).
Do not query ClickHouse person tables with raw SQL; go through HogQL.

**Avoid reading `properties` from personhog wherever possible.**
The long-term direction is for the personhog API to not surface the properties field to users at all.
If your code needs a person's properties, get them from ClickHouse, even when you already have the person's identity from personhog.

The current exemption: there is no sanctioned primitive yet for "look up one person and get its properties" from ClickHouse, so some existing paths read properties off a personhog point lookup (for example the person detail endpoint, flag test evaluation, and single-person reads in conversations and replay).
These are tolerated until that primitive exists, but do not extend the pattern to bulk reads, and prefer the ClickHouse route when one is available for your case (see `build_person_properties_at_time` in `posthog/models/person/point_in_time_properties.py` for an example of identity-from-personhog, properties-from-ClickHouse).

## Why the split

Personhog is the source of truth for identity: which person a distinct ID maps to right now, whether a person exists, and which distinct IDs belong to it.
It is Postgres-backed and read-after-write consistent, which is what identity decisions need.
But it serves point lookups over gRPC, so hauling large property JSON blobs through it is expensive and does not scale to bulk reads.

ClickHouse is the analytical store.
It is built for scanning, filtering, and returning many rows with their properties in one query, and every insight already reads persons from it.
Its person data lands asynchronously, so it can lag ingestion by a short window — acceptable for displaying and searching properties, not acceptable for deciding who a distinct ID belongs to.

So the split follows the shape of the question:

| Question                                           | Source     |
| -------------------------------------------------- | ---------- |
| Which person is this distinct ID?                  | personhog  |
| Does this person UUID exist? What are its IDs?     | personhog  |
| What are this person's properties?                 | ClickHouse |
| Which persons match this filter/search?            | ClickHouse |
| Give me these 500 persons with their properties    | ClickHouse |
| Delete/split this person, change cohort membership | personhog  |

## Legacy paths

Some code still hydrates person properties through personhog and is migrating toward ClickHouse:

- `PersonStrategy.get_actors` (`posthog/hogql_queries/actor_strategies.py`) fetches properties via personhog after ClickHouse has selected the actor UUIDs.
- `get_serialized_people` (`posthog/queries/actor_base_query.py`), used by the persons list API.

Do not copy these patterns into new code: bulk hydration of persons with properties always belongs in ClickHouse.

## Related docs

- [`posthog/personhog_client/README.md`](../../posthog/personhog_client/README.md) — client usage, routed helpers, testing with the fake client.
- Direct ORM or raw SQL access to person tables is banned entirely; the personhog client README lists the covered tables.
