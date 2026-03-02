## Problem

The Django service currently accesses person data directly via the ORM against PostgreSQL.
We want to migrate these accesses to go through the `personhog-router` gRPC service instead,
but we have no Python client for it and no infrastructure to support a gradual rollout.

## Changes

This PR sets up the foundation for the migration — proto generation, the gRPC client, and rollout gating.
It does **not** replace any ORM call sites yet; that's a follow-up.

**Proto generation pipeline (`bin/generate_personhog_proto.sh`)**

- Added `grpcio`/`protobuf` (runtime) and `grpcio-tools`/`protoletariat` (dev) to `pyproject.toml`
- Generated stubs are checked in at `posthog/personhog_client/proto/generated/`
- The script is needed because `grpc_tools.protoc` generates Python files with absolute imports
  (e.g. `from personhog.types.v1 import common_pb2`) which don't resolve when the generated
  code lives nested under `posthog/personhog_client/proto/generated/`. The script runs
  `protoletariat` as a post-processing step to rewrite these to relative imports so the
  stubs work as a normal Python package without `sys.path` hacks.
- The two-pass approach (generate stubs, then rewrite imports) is standard for protobuf
  Python codegen in monorepos where the generated output directory doesn't match the proto
  package structure.

**Lint exclusions for generated proto stubs**

- Added `./posthog/personhog_client/proto/generated` to ruff's `exclude` list in `pyproject.toml`
- Added the same path to the lint-staged negation glob in `package.json` — the husky
  pre-commit hook runs `lint-staged` which passes explicit file paths to ruff via
  `hogli lint:python:fix`. Ruff's `exclude` list is ignored when files are passed explicitly,
  so the lint-staged glob pattern must exclude them (same approach used for `posthog/hogql/grammar/`).

**Client module (`posthog/personhog_client/`)**

- `proto/__init__.py` — re-exports all proto types for ergonomic imports
- `client.py` — synchronous `PersonHogClient` wrapping `PersonHogServiceStub` with typed methods for every RPC, plus a thread-safe `get_personhog_client()` singleton
- `gate.py` — `use_personhog()` rollout gate checking `PERSONHOG_ENABLED`, `PERSONHOG_ADDR`, and `PERSONHOG_ROLLOUT_PERCENTAGE`

**Settings (`posthog/settings/personhog.py`)**

- `PERSONHOG_ADDR` — gRPC address of the personhog router
- `PERSONHOG_ENABLED` — kill switch (bool)
- `PERSONHOG_TIMEOUT_MS` — per-call timeout (default 5000ms)
- `PERSONHOG_ROLLOUT_PERCENTAGE` — percentage of requests routed through gRPC (0-100)
- Lives in its own settings module so all Django processes (web, celery, temporal) get it

**CI (`ci-proto.yml`)**

- Added `python-codegen` job that installs `grpcio-tools` and `protoletariat`, regenerates stubs, and diffs against what's checked in — fails if they're stale
- Wired into the existing `proto_checks` gate job
- Path filter expanded to trigger on generated files and the generation script

**Docs**

- Updated `proto/README.md` with Python language binding, regeneration instructions, and updated CI/workflow sections

## How did I test this?

- Ran `bin/generate_personhog_proto.sh` — produces all expected `_pb2.py` files
- Verified proto imports and message construction work correctly
- `ruff check posthog/personhog_client/` passes clean
- Verified `get_personhog_client()` returns `None` when `PERSONHOG_ADDR` is not set
- **End-to-end verification that the client works against a live personhog stack:**
  1. Temporarily wired `get_person_and_distinct_ids_for_identifier()` to use the personhog client behind the rollout gate
  2. Ran `personhog-replica` (connected to local `posthog_persons` DB) and `personhog-router` locally
  3. Set `PERSONHOG_ENABLED=true`, `PERSONHOG_ADDR=localhost:50052`, `PERSONHOG_ROLLOUT_PERCENTAGE=100`
  4. Hit `GET /api/projects/1/persons/properties_at_time/?person_id=<uuid>&timestamp=...`
  5. Confirmed data returned correctly via gRPC — router metrics showed requests for `GetPersonByUuid` and `GetDistinctIdsForPerson`, replica logged the incoming calls
  6. Verified fallback: stopped the router, re-hit the endpoint, data still returned via ORM
