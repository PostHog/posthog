---
name: adding-personhog-rpc
description: >
  Guide for adding a new RPC to personhog-replica and personhog-router.
  Covers eligibility checks, proto definition, code generation for Python and Node.js clients,
  Rust implementation (storage trait, postgres queries, service handler, router wiring),
  and index compatibility validation. Use when adding a new gRPC endpoint to personhog,
  migrating a Django ORM query to personhog, or extending the personhog service API.
---

# Adding a personhog RPC

This skill walks through adding a new RPC end-to-end:
proto definition, code generation, Rust implementation, and client updates.

## Before you start: eligibility check

Personhog serves person, distinct ID, group, group type mapping, cohort membership, and feature flag hash key override data.
If the data being accessed doesn't live in one of these tables, this RPC doesn't belong in personhog:

| Table                                | Data category | Routing                                                      |
| ------------------------------------ | ------------- | ------------------------------------------------------------ |
| `posthog_person`                     | PersonData    | Reads: replica (eventual) or leader (strong). Writes: leader |
| `posthog_persondistinctid`           | PersonData    | Same as person                                               |
| `posthog_group`                      | NonPersonData | All ops: replica                                             |
| `posthog_grouptypemapping`           | NonPersonData | All ops: replica                                             |
| `posthog_cohortpeople`               | NonPersonData | All ops: replica                                             |
| `posthog_featureflaghashkeyoverride` | NonPersonData | All ops: replica                                             |
| `posthog_personoverride`             | PersonData    | Reads/writes follow person routing                           |
| `posthog_personlessdistinctid`       | PersonData    | Same as person                                               |

If the table is not listed above, **stop** — this data should not go through personhog.

## Step 0: design the data access pattern

Before writing any proto, figure out the SQL query you need.
Then validate it against the available indexes — see [references/database-indexes.md](references/database-indexes.md).

Key questions:

- What table(s) does this query hit?
- Does the WHERE clause match an existing index? Every query must be an index scan, never a sequential scan.
- Is this a read or write? This determines routing (see table above).
- For reads: does the caller need strong consistency (primary pool) or is eventual (replica pool) acceptable?
- For batch lookups: is the batch within a single team or cross-team?

## Step 1: define proto messages and RPC

All proto files live in `proto/personhog/`.
See [references/proto-conventions.md](references/proto-conventions.md) for message conventions and a worked example.

### Where to add what

1. **Message types** → `proto/personhog/types/v1/<domain>.proto` (person.proto, group.proto, cohort.proto, feature_flag.proto, or common.proto)
2. **Service RPC** → `proto/personhog/service/v1/service.proto` (the public API clients call)
3. **Replica RPC** → `proto/personhog/replica/v1/replica.proto` (the internal API the router delegates to)
4. **Leader RPC** → `proto/personhog/leader/v1/leader.proto` (only if this is a person-data write routed to leader)

The service and replica protos must both declare the RPC with identical signature.
The router delegates from service → replica (or leader) transparently.

## Step 2: generate client stubs

### Python

```bash
bin/generate_personhog_proto.sh
```

Then update three files:

- `posthog/personhog_client/proto/__init__.py` — add re-exports for new request/response message types
- `posthog/personhog_client/client.py` — add a wrapper method matching the pattern of existing methods
- `posthog/personhog_client/fake_client.py` — implement the method for test use

### Node.js

```bash
cd nodejs && pnpm run generate:personhog-proto
```

Then update:

- `nodejs/src/ingestion/personhog/client.ts` — add a wrapper method matching the pattern of existing methods
- `nodejs/src/ingestion/personhog/client.test.ts` — add a default stub to `SERVICE_DEFAULTS` for the new RPC

### Rust

No generation step needed — tonic regenerates on `cargo build`.
But you must implement the RPC (next step), or the build will fail.

## Step 3: implement in Rust

The compiler guides you — once the proto is defined, `cargo build` errors tell you exactly which trait methods are missing.

### 3a. Storage layer (personhog-replica)

1. **Add a trait method** in `rust/personhog-replica/src/storage/traits/<domain>.rs`
2. **Implement the query** in `rust/personhog-replica/src/storage/postgres/<domain>.rs`
   - Use `sqlx::query_as!` or `sqlx::query!` macros
   - Add timing instrumentation via `DB_QUERY_DURATION` and `DB_ROWS_RETURNED` metrics
   - Use `self.replica_pool` for reads, `self.primary_pool` for writes
   - Return early for empty batch inputs
3. **Add storage tests** in `rust/personhog-replica/tests/storage_tests.rs`

### 3b. Service layer (personhog-replica)

1. **Add the RPC handler** in `rust/personhog-replica/src/service/mod.rs`
   - Extract fields from the proto request
   - Call the storage trait method
   - Convert storage results to proto responses
   - Map storage errors to tonic `Status` codes
2. **Add service tests** in `rust/personhog-replica/tests/service_tests.rs`

### 3c. Router wiring (personhog-router)

1. **Add the method** to `rust/personhog-router/src/router/mod.rs`
   - Use the `route_request` function (imported from `routing.rs`) with the correct `DataCategory` and `OperationType`
   - Call the replica (or leader) backend
   - Use the `call_backend!` macro for instrumentation
2. **Add the service impl** to `rust/personhog-router/src/service/mod.rs`
   - Invoke the `route_request!` macro (defined at the top of this file) to delegate to the router
3. **Add to the backend trait** in `rust/personhog-router/src/backend/mod.rs` and implement in `replica.rs`
4. **Add router tests** in `rust/personhog-router/tests/`

Use `rstest` parameterized tests where multiple variations of the same behavior are being tested.

## Step 4: verify

```bash
cargo build -p personhog-proto
cargo build -p personhog-replica
cargo build -p personhog-router
cargo test -p personhog-replica
cargo test -p personhog-router
```

## Checklist

- [ ] Query uses an existing index (no seq scans)
- [ ] Proto messages added to `types/v1/<domain>.proto`
- [ ] RPC added to both `service.proto` and `replica.proto` (and `leader.proto` if needed)
- [ ] Python stubs generated, `proto/__init__.py` updated, `client.py` method added, `fake_client.py` updated
- [ ] Node.js stubs generated, `client.test.ts` SERVICE_DEFAULTS updated
- [ ] Rust storage trait + postgres impl + service handler + router wiring all implemented
- [ ] Tests added at storage, service, and router layers
- [ ] `cargo build` and `cargo test` pass for all three crates
