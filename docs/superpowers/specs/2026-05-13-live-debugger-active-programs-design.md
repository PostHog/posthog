# Live Debugger: Active Programs Endpoint

## Context

The `libdebugger` Python runtime (sibling repo `libdebugger`) polls PostHog for the list of
hogtrace programs to install in the running process. Its `HogTraceManager._fetch_programs`
loop hits:

    GET /api/projects/@current/live_debugger/programs/active

with a personal API key, and decodes the response body as a hogtrace `ProgramList`
protobuf via `ProgramList.from_bytes(content)`.

Today the route does not exist. The existing `LiveDebuggerProgramViewSet`
(`products/live_debugger/backend/api.py`) provides CRUD for the `LiveDebuggerProgram`
model — installing, listing (JSON, code-omitted), retrieving, and soft-uninstalling
programs — but exposes no machine-facing endpoint that returns compiled bytecode.

This spec adds the missing endpoint so the agent runtime can fetch and install
active programs.

## Goals

1. Provide a machine-facing endpoint that returns the team's installed hogtrace
   programs as a single `ProgramList` protobuf payload.
2. Authenticate via personal API key (what libdebugger sends), team-scoped via the
   standard `@current` resolution.
3. Compile each program's stored source via `hogtrace.compile()` + `hogtrace.package()`
   at request time. Compile failures are skipped (logged), so one bad program cannot
   take down the polling fleet.
4. Ensure each returned `Program.hash` actually reflects the program's content, so
   libdebugger's reconcile-diff (`current.hash != incoming.hash` → `update`) works.

## Non-goals

- No frontend changes. This endpoint is consumed by `libdebugger`, not by the PostHog UI.
- No new MCP tool. The existing program CRUD MCP tools already cover human/agent program
  management; the active endpoint is for the runtime poller.
- No caching of compiled bytecode in the DB. Recompile per request. Revisit if the
  endpoint shows up in slow-query traces.
- No support for paging. A team's installed-program count is expected to be small (single
  digits) for the foreseeable future. If it grows, libdebugger's polling model will need
  to change before any server-side paging matters.

## Design

### Route and method

|                |                                                                                        |
| -------------- | -------------------------------------------------------------------------------------- |
| Method         | `GET`                                                                                  |
| Path           | `/api/projects/:project_id/live_debugger/programs/active` (with `@current` resolution) |
| Auth           | `PersonalAPIKeyAuthentication`, `SessionAuthentication`                                |
| Required scope | `live_debugger:read`                                                                   |
| Content-Type   | `application/octet-stream`                                                             |
| Body           | hogtrace `ProgramList` protobuf bytes                                                  |

Implemented as a new `active` action on `LiveDebuggerProgramViewSet`, in
`products/live_debugger/backend/api.py`. The existing `active_breakpoints` action on
`LiveDebuggerBreakpointViewSet` is a structural analogue but is **not** the right
template for auth: it uses `ProjectSecretAPIKeyAuthentication`, whereas libdebugger
sends a personal API key.

### Query parameters

None. The libdebugger client passes none, and the contract is "give me the full active
set for this team."

### Tenant scoping

- Scoped to `team` (resolved by `TeamAndOrgViewSetMixin` from `@current`).
- Filter: `status = LiveDebuggerProgram.Status.INSTALLED`.
- Uninstalled programs are retained for history but never returned here.

The "by the api key organization" phrasing in the original ask resolves to "the team
selected by the personal API key's `@current`" — which is the existing pattern and the
only one consistent with PostHog's `team_id` tenant boundary.

### Per-request flow

1. Query installed programs for `self.team`.
2. For each row:
   - Compile its `code` field via `hogtrace.compile(code)` to get a `ProgramBytecode`.
   - Wrap into a `Program` via `hogtrace.package(str(program.id), bytecode)` and
     serialize to wire bytes via `program.to_bytes()`. Hogtrace currently emits
     `hash="test"` here; we don't depend on that field.
   - Compute `digest = sha256(program_bytes).hexdigest()`.
   - Parse `program_bytes` with our Python proto bindings (see below), overwrite the
     `hash` field with `digest`, and append to the list of wire-format
     `HogTraceProgram` messages.
   - On `hogtrace.CompilationError` / `ValueError` / any unexpected exception
     during compile or package, log a warning with the program id and skip the
     row.
3. Build a `ProgramList` proto message containing the patched programs, set
   `retrieved_at` to `int(time.time())`, and serialize to bytes.
4. Return `HttpResponse(program_list_bytes, content_type="application/octet-stream")`.

### Program hash

`Program.hash` is what libdebugger's reconcile-diff uses to decide whether to
`update_program` (`if installed.hash != incoming.hash`). Today, hogtrace's
`package()` hardcodes `hash: "test"` in its Rust binding
(`src/python_bindings.rs` line 42), so the value on the wire is useless. Rather
than patch hogtrace, we overwrite the hash on the server when assembling the
response.

**Hash content**: SHA-256 (hex) of the wire bytes hogtrace produces for the
program (`Program.to_bytes()` output, including the placeholder hash). The
placeholder is constant, so the digest is fully determined by the rest of the
bytecode and changes if and only if the compiled program content changes. This
gives libdebugger a stable, real signal for its diff.

### Python proto bindings

We generate Python protobuf bindings from `hogtrace/proto/bytecode.proto` and
vendor them into the live_debugger product (e.g. `products/live_debugger/backend/_proto/`).
The hogtrace `.proto` is the source of truth; we only need read/write access to
the `HogTraceProgram.hash` field and the `ProgramList` wrapper, so any small drift
in unrelated fields is irrelevant as long as the file is regenerated when the
proto changes. The implementation plan decides whether to commit pre-generated
`_pb2.py` files or run `protoc` at build time.

### Failure modes

| Condition                                   | Response                                                                                       |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| No installed programs for the team          | `200 OK`, empty `ProgramList` (zero `programs`)                                                |
| One or more programs fail to compile        | `200 OK`, `ProgramList` contains only the programs that compiled successfully; failures logged |
| All programs fail to compile                | `200 OK`, empty `ProgramList`; failures logged                                                 |
| Auth missing / invalid                      | `401 Unauthorized`                                                                             |
| Personal API key lacks `live_debugger:read` | `403 Forbidden`                                                                                |

The "skip on compile failure" choice keeps the poller useful when only some
programs are broken. The alternative — returning `500` — would freeze every
client's program set until an operator manually edits the broken program.

### Query tagging

Tag the team's program-query for observability, consistent with the existing
`events` action:

    tag_queries(product=Product.LIVE_DEBUGGER, feature=Feature.QUERY)

This is a Postgres query (not ClickHouse) but the tag is cheap and we may add
ClickHouse-backed metrics later.

### OpenAPI / schema

Annotate with `@extend_schema`:

- Summary: "Get compiled active programs (External API)"
- Description explains the personal-API-key auth, the `application/octet-stream`
  payload, and the protobuf shape (link to hogtrace's `ProgramList` proto definition
  if practical).
- Response: `200` with `OpenApiTypes.BINARY`; `401`, `403`.

The response is binary, so this endpoint does not generate a typed TypeScript client
(intentional — no PostHog frontend consumes it). drf-spectacular will surface it in
the OpenAPI spec as a binary response, which is correct.

## Out-of-repo dependency

None. The hash placeholder in `hogtrace.package()` is worked around in the
endpoint by re-emitting the protobuf with the correct hash. `libdebugger` only
reads `Program.hash` from the wire and needs no changes.

## Testing

Tests live alongside the viewset in `products/live_debugger/backend/test_api.py`.

Backend test cases (all parameterized where they share structure):

1. **Happy path**: Two installed programs for the team → `200`, payload deserializes
   via `ProgramList.from_bytes()`, contains two programs with matching `id`s and
   distinct, deterministic `hash`es.
2. **Status filter**: Three programs in the team's DB — one installed, one
   uninstalled, one installed with no compile issues. Response includes the two
   installed and excludes the uninstalled.
3. **Team isolation**: Programs from a sibling team in the same org do **not**
   appear in this team's response.
4. **Compile-failure skip**: Insert one valid program and one with intentionally
   broken hogtrace source. Response has `200` and contains only the valid
   program. Captures the log message at WARN.
5. **Empty set**: Team with zero installed programs returns `200` and an empty
   `ProgramList`.
6. **Auth — personal API key**: Request with a valid personal API key authenticates
   and returns the team's programs.
7. **Auth — missing key**: Request with no auth returns `401`.
8. **Auth — wrong scope**: Personal API key without `live_debugger:read` scope
   returns `403`.
9. **Hash stability**: Same program code → same hash across two consecutive calls.
   Editing the code changes the hash.
10. **Content-Type**: Response has `Content-Type: application/octet-stream`.

## Migration / rollout

- No DB migration. The `LiveDebuggerProgram` model already has everything needed.
- No feature flag. The endpoint is additive and behind an existing scope.
- Backwards compatibility: no existing clients — this is a green-field route.

## Risks

- **Hogtrace version drift.** If hogtrace's bytecode format changes between server
  and client, libdebugger will reject the payload. Out of scope for this spec, but
  worth noting that `BYTECODE_VERSION` is already part of the `CompiledProgram`
  proto, so libdebugger can detect mismatches.
- **Compile cost in the request path.** Hogtrace compilation is "fast" per its
  README but unbounded in worst case. With single-digit programs per team, recompile
  per request is fine. If a team accumulates dozens of programs, add a per-row
  cache keyed by `(id, updated_at)`.
- **Cross-product imports.** `products/live_debugger` is not isolated (no
  `backend:contract-check` in `package.json`). No facade changes needed today.
