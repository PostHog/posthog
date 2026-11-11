# personhog_client

Python gRPC client for the personhog service — the required interface for all person, group, and cohort data access from Django.

## Why this client exists

Personhog is an internal service that owns the source of truth for person-related data.
**All Django code must use this client (or the routed helpers built on it) instead of querying person/group tables via the ORM or raw SQL.**
Direct ORM queries like `Person.objects.filter(...)` or `PersonDistinctId.objects.filter(...)` are not allowed for new code.

Routed helpers that handle the gRPC call and metrics already exist in
`posthog/models/person/util.py` and `posthog/models/group_type_mapping.py` — use these when one fits your use case.
When no existing helper covers your needs, follow the `_personhog_routed()` pattern in `posthog/models/person/util.py`.
personhog is the sole read path — there is no ORM fallback.

## Scope: identity questions only

Personhog is for **identity resolution and point lookups**: resolving a distinct ID to a person, checking a person exists, fetching a single person (or a small known set) by id or UUID, and lifecycle writes (deletes, splits, cohort membership).

It is **not** for property-shaped or bulk-shaped reads.
Loading person properties, hydrating lists of persons, and searching or filtering persons all belong in ClickHouse (HogQL over the `persons` table, `ActorsQueryRunner`).
Avoid reading the `properties` field from personhog where possible — the long-term direction is for the API to not surface it to users at all.
Single-person point lookups that need properties are currently exempt where no ClickHouse primitive exists for them; do not extend that to bulk reads.

See [docs/internal/person-data-access.md](/docs/internal/person-data-access.md) for the full guidelines and rationale.

## Database tables

The following tables are managed by personhog.
Do not query them directly — use the routed helpers or client RPCs.

| Table                                | Django model                 | Description                        |
| ------------------------------------ | ---------------------------- | ---------------------------------- |
| `posthog_person`                     | `Person`                     | Core person records                |
| `posthog_persondistinctid`           | `PersonDistinctId`           | Distinct ID → person mappings      |
| `posthog_cohortpeople`               | `CohortPeople`               | Static cohort membership           |
| `posthog_group`                      | `Group`                      | Group records                      |
| `posthog_grouptypemapping`           | `GroupTypeMapping`           | Group type → column index mappings |
| `posthog_personoverride`             | `PersonOverride`             | Person merge overrides             |
| `posthog_pendingpersonoverride`      | `PendingPersonOverride`      | Pending person merge overrides     |
| `posthog_flatpersonoverride`         | `FlatPersonOverride`         | Flattened person overrides         |
| `posthog_featureflaghashkeyoverride` | `FeatureFlagHashKeyOverride` | Feature flag hash key overrides    |
| `posthog_personoverridemapping`      | `PersonOverrideMapping`      | Person override mappings           |

## Client singleton

`get_personhog_client()` returns a thread-safe singleton `PersonHogClient` instance, configured from Django settings.
Returns `None` when `PERSONHOG_ADDR` is not set (e.g. in local dev without personhog running).

## Proto converters

`converters.py` provides functions to convert gRPC proto messages into Django model instances or dicts:

- `proto_person_to_model()` — converts a proto `Person` to an unsaved Django `Person` instance
- `proto_group_type_mapping_to_dict()` — converts a proto `GroupTypeMapping` to a dict matching the ORM `.values()` shape
- `proto_group_type_mapping_to_result()` — converts to a lightweight `GroupTypeMappingResult` dataclass

These ensure that existing serializers and property accessors work without modification.

## Available RPCs

The `PersonHogClient` in `client.py` exposes typed methods for every RPC:

**Person lookups:**
`get_person`, `get_persons`, `get_person_by_uuid`, `get_persons_by_uuids`,
`get_person_by_distinct_id`, `get_persons_by_distinct_ids_in_team`

**Distinct ID operations:**
`get_distinct_ids_for_person`, `get_distinct_ids_for_persons`

**Person deletes:**
`delete_persons`, `delete_persons_batch_for_team`, `delete_tombstoned_persons` (deletes only while still tombstoned and, for `bounded_persons`, at or below each person's `max_version`; check `version_guard_applied` on the response; a bounded number of dependent rows per call; persons it did not finish come back as pending and are sent again; used by the persons cleanup drain)

**Person split:**
`split_person` — splits distinct_ids off a person onto new persons (max 250 per request); the sole write path for person splits, with no ORM fallback

**Lifecycle sagas (identity server):**
`client.lifecycle.delete_persons` runs the fenced delete saga for up to 250 person ids of one team and returns one outcome per requested id (`DELETED`, `NOT_FOUND`, `SKIPPED_CONFLICT`).
The sagas live under `client.lifecycle` because the facade has a `delete_persons` too, and the two go to places with opposite consistency: the facade writes the replica's database directly, a saga fences the person's leader first.
They go out on a second channel to `PERSONHOG_LIFECYCLE_ADDR` (a router with the identity proxy enabled); without that setting `client.lifecycle.configured` is false and every saga method raises `PersonHogLifecycleUnavailable`.
The lifecycle service is the only identity-server surface Django has: `bin/generate_personhog_proto.sh` emits no stubs for `personhog.identity.v1`, so the ingestion RPCs (`GetOrCreate*`, `MergePersons`) cannot be called from Python.
The call waits for the saga to complete, so its deadline is `PERSONHOG_LIFECYCLE_TIMEOUT_MS` rather than `PERSONHOG_TIMEOUT_MS`.
Every request carries a caller-generated `op_id`. Retry a transient failure with the same `op_id` and the identical `person_ids` list; the retry attaches to the existing operation and returns its recorded outcome.
A `FAILED_PRECONDITION` with a reason from `semantic_refusal_reason()` (in `interceptor.py`) is final: never retry it under the same `op_id`. The identity server's own reason is `op_id_reused` (the `op_id` belongs to a different request; reissue under a fresh one). The leader's reasons (`release-unverified`, `uuid-mismatch`, `no-lifecycle-db`) pass through the saga unchanged and mean the operation cannot finish as issued; surface them rather than looping.
The request and response types are re-exported from `posthog.personhog_client.proto` as `LifecycleDeletePersonsRequest` and `LifecycleDeletePersonsResponse`, because the facade's delete messages share their names.
Django's person deletes reach it through `tombstone_persons_via_lifecycle` in `posthog/models/person/util.py` when `PERSONHOG_WRITE_PATH` is `leader`; on `replica` they stay on the facade's TOMBSTONE delete. The leader path must be set before ingestion moves to the leader, because a facade tombstone never reaches the leader's cache and the next leader write revives the person. The op_id is `uuid5(run id, team, sorted ids)`, where the run id is the caller's run plus its attempt number (the Celery task id and retry count, the Temporal workflow run id and activity attempt, the Dagster run id), so a redelivery inside one attempt attaches to its op and each scheduled retry starts a new one; a new op is needed because the server records an all-conflict op as completed and replays it.
Django produces nothing to ClickHouse on this path: the saga's publish outbox carries the distinct-id tombstones and the person changelog carries the person row.

**Version floors:**
`ensure_person_version_floors` (raise each tombstone to a minimum version, inserting a tombstone where no row exists, and leave live rows unchanged; a lost insert race fails the whole request with `FAILED_PRECONDITION`).
Each write takes at most 250 keys in one transaction. Use the helper in `posthog/models/person/util.py`: it batches and retries a lost race.

**Cohort membership:**
`check_cohort_membership`, `count_cohort_members`, `insert_cohort_members`,
`delete_cohort_member`, `delete_cohort_members_bulk`, `list_cohort_member_ids`

**Groups:**
`get_group`, `get_groups`, `get_groups_batch`

**Group type mappings:**
`get_group_type_mappings_by_team_id`, `get_group_type_mappings_by_team_ids`,
`get_group_type_mappings_by_project_id`, `get_group_type_mappings_by_project_ids`

## Testing

Use the `FakePersonHogClient` for tests.
It implements the same interface as `PersonHogClient` using real proto messages,
so the full converter pipeline is exercised end-to-end.

```python
from posthog.personhog_client.fake_client import fake_personhog_client

def test_something(self):
    with fake_personhog_client() as fake:
        fake.add_person(team_id=1, person_id=42, uuid="some-uuid", distinct_ids=["user@example.com"])
        fake.add_group_type_mapping(project_id=1, group_type="org", group_type_index=0)
        fake.add_group(team_id=1, group_type_index=0, group_key="posthog")
        fake.add_cohort_membership(person_id=42, cohort_id=7)

        # code under test calls get_personhog_client() and gets the fake
        result = get_person_by_uuid(1, "some-uuid")
        assert result is not None

        # Assert specific RPCs were called
        fake.assert_called("get_person_by_uuid", times=1)
```

## Observability

The client emits Prometheus metrics at multiple layers:

**Routing metrics** (`metrics.py`):

- `personhog_routing_total` — counts personhog reads per operation
- `personhog_routing_errors_total` — personhog read errors per operation
- `personhog_team_mismatch_total` — persons dropped because personhog returned a mismatched team_id

**gRPC request metrics** (`interceptor.py`):

- `personhog_django_grpc_request_duration_seconds` — request latency histogram
- `personhog_django_grpc_requests_total` — request count by method and status (timeouts are `status="DEADLINE_EXCEEDED"`)

**Channel metrics** (`client.py`):

- `personhog_django_grpc_channel_state` — current gRPC channel connectivity state
- `personhog_django_grpc_channel_state_transitions_total` — state transition count
- `personhog_django_grpc_connection_establishment_seconds` — time to establish connection

## Directory layout

- `client.py` — `PersonHogClient` with typed methods for each RPC, plus `get_personhog_client()` singleton
- `converters.py` — proto-to-Django conversion functions
- `fake_client.py` — `FakePersonHogClient` for tests
- `interceptor.py` — gRPC interceptors for client name headers and request metrics
- `metrics.py` — Prometheus counters for routing decisions
- `proto/__init__.py` — convenience re-exports of proto types

The auto-generated protobuf stubs live outside this directory, in [`packages/personhog-proto`](/packages/personhog-proto/README.md).
They install as the top-level `personhog` package. Do not edit them by hand.

For updating proto definitions, see [`proto/README.md`](/proto/README.md).
