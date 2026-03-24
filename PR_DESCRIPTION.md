## Problem

We're incrementally migrating Django ORM reads against the persons database to use the personhog gRPC service. Four call sites were already migrated with a proven dual-read pattern (`use_personhog()` gate → try gRPC → metrics → ORM fallback). The remaining person-by-UUID and person-by-distinct-ID read paths still hit the ORM directly, blocking us from fully decoupling Django from the persons database.

## Changes

**New helpers in `posthog/models/person/util.py`:**

- `get_person_by_uuid(team_id, uuid)` — single person lookup by UUID with dual-read (gRPC + ORM fallback)
- `get_person_by_distinct_id(team_id, distinct_id)` — single person lookup by distinct ID with dual-read
- `validate_person_uuids_exist(team_id, uuids)` — batch UUID existence check with dual-read

All three follow the same pattern as the existing `get_persons_by_distinct_ids` and `get_persons_by_uuids`: gate check → gRPC call with team_id validation → metrics → ORM fallback on error.

**`get_distinct_ids_for_subquery` optimization (`person.py`):**
Added early return when `_distinct_ids` is already populated from personhog, avoiding two redundant `PersonDistinctId` ORM queries.

**Personhog gate middleware (`personhog_client/middleware.py` + `gate.py`):**
Added `PersonHogGateMiddleware` that pins the `use_personhog()` decision for the lifetime of an HTTP request. The first call rolls the dice, and all subsequent calls on the same thread reuse that decision — guaranteeing that all personhog-routed reads within a single request consistently use the same backend (either all gRPC or all ORM). This avoids mixed-source reads during partial rollout.

**Converter fix (`personhog_client/converters.py`):**
`proto_person_to_model` now wraps `person.uuid` with `uuid.UUID()` so the returned Person has the same UUID type as the ORM, preventing subtle type mismatches downstream.

**Person by UUID call sites (7 sites):**

- `point_in_time_properties.py` — both UUID and distinct_id paths
- `events_query_runner.py`, `sessions_query_runner.py`, `query_event_list.py` — personId filtering
- `api/person.py` `delete_property` — person lookup before property deletion
- `api/cohort.py` `_handle_static` + `add_persons_to_static_cohort` — UUID validation via `validate_person_uuids_exist`
- `cohort/cohort.py` `remove_user_by_uuid` — person lookup before cohort removal

**Person by distinct ID call sites (3 sites):**

- `session_recording_api.py` — uses `get_persons_by_distinct_ids` when personhog gate is on; preserves original lightweight ORM path (intentionally sets `_distinct_ids = [single_id]` to avoid fetching all distinct IDs)
- `tickets.py` — uses `get_persons_by_distinct_ids`
- `cohort/cohort.py` `_get_uuids_for_distinct_ids_batch` — uses `get_persons_by_distinct_ids` when personhog gate is on; preserves original lightweight `values_list` ORM path (no model instantiation)

**ORM path performance:** Verified that all ORM fallback paths produce identical queries to the original code. Two call sites (`session_recording_api.py` and `cohort._get_uuids_for_distinct_ids_batch`) had original ORM code that was deliberately optimized (lightweight queries, avoiding full model instantiation or fetching all distinct IDs). These keep their original ORM code and only route through `get_persons_by_distinct_ids` when the personhog gate is on.

## How did you test this code?

- **New routing + filtering tests** (`test_util_personhog_single_person_routing.py`, 21 tests) covering all 3 new helpers:
  - Routing tests for `get_person_by_uuid`, `get_person_by_distinct_id`, `validate_person_uuids_exist` — each verifies gate on/success → personhog, gate on/failure → ORM fallback, gate off → ORM directly
  - gRPC fetch tests for `_fetch_person_by_uuid_via_personhog`, `_fetch_person_by_distinct_id_via_personhog`, `_validate_uuids_via_personhog` — covering happy path, person not found, empty person ID, team mismatch, and wrong-team filtering
- **New cohort personhog tests** (`test_cohort_personhog.py`, 15 tests) covering:
  - `_get_uuids_for_distinct_ids_batch` — matching, empty input, no match, cross-team isolation, deduplication, mixed found/missing, multiple persons, ORM fallback when gate off
  - `remove_user_by_uuid` — removal, idempotent removal (person not in cohort), nonexistent person, cross-team isolation, count update, count error resilience, personhog call verification
- **New gate + middleware tests** (`test_gate.py`, 117 lines) covering pin/unpin behavior, per-request consistency, and rollout percentage logic
- Existing personhog routing tests still pass: `pytest posthog/models/person/test/test_util_personhog_routing.py` (7 tests)
- Existing fake client and converter tests still pass: `pytest posthog/personhog_client/test_fake_client.py posthog/personhog_client/test_converters.py` (45 tests)
- All changes are behind the `use_personhog()` gate (controlled by `PERSONHOG_ROLLOUT_PERCENTAGE`), so with the gate off (default), behavior is identical to before
- Traced each call site's ORM fallback path to confirm query equivalence with the original code — no regressions to query count or data fetched

### Local Development Testing

Exercised the following code paths through the respective endpoints:

`events_query_runner.py` — EventsQuery with personId
**Endpoint:** `POST /api/environments/1/query/` (EventsQuery)
**Call site:** `calculate()` → `get_person_by_uuid()`

`sessions_query_runner.py` — SessionsQuery with personId
**Endpoint:** `POST /api/environments/1/query/` (SessionsQuery)
**Call site:** `calculate()` → `get_person_by_uuid()`

`query_event_list.py` — Legacy event list
**Endpoint:** `GET /api/environments/1/events/?person_id=<uuid>`
**Call site:** `_filter_by_person_id_or_distinct_id()` → `get_person_by_uuid()`

`api/person.py` — delete_property
**Endpoint:** `POST /api/environments/1/persons/<uuid>/delete_property/`
**Call site:** `delete_property()` → `get_person_by_uuid()`

`api/cohort.py` — \_handle_static (create static cohort)
**Endpoint:** `POST /api/projects/1/cohorts/` (with `_create_static_person_ids`)
**Call site:** `_handle_static()` → `validate_person_uuids_exist()`

`api/cohort.py` — add_persons_to_static_cohort
**Endpoint:** `PATCH /api/projects/1/cohorts/<id>/add_persons_to_static_cohort/`
**Call site:** `add_persons_to_static_cohort()` → `validate_person_uuids_exist()`

`models/cohort/cohort.py` — remove_user_by_uuid
**Endpoint:** `PATCH /api/projects/1/cohorts/<id>/remove_person_from_static_cohort/`
**Call site:** `remove_user_by_uuid()` → `get_person_by_uuid()`

`cohort.py` — \_get_uuids_for_distinct_ids_batch
**Trigger:** Static cohort CSV upload with distinct IDs
**Call site:** `_get_uuids_for_distinct_ids_batch()` → `get_persons_by_distinct_ids()`

Error handling — ORM fallback

- Brought personhog-router/personhog-replica down and made a call to events_query_runner and we still returned a person
