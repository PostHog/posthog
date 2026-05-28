# Agentic CLI — Phase 1 Result

Phase 0 proved Rust-native is viable. Phase 1 makes it real: the manifest is now **generated
from the MCP pipeline for all enabled tools**, the Rust interpreter consumes that generated
manifest, and a **live conformance harness** asserts the interpreter's requests match the
**real MCP handlers** — not a re-derivation of them.

## What was built

### 1. Manifest generation in the MCP pipeline

- `services/mcp/scripts/generate-cli-manifest.ts` — `generateCliManifest()` emits the declarative
  manifest from the same resolved YAML + OpenAPI inputs the MCP handlers use (reusing
  `composeToolSchema`, `resolveDescription`, `extractKindFromSchemaRef`).
- Hooked into `generate-tools.ts` (runs as part of `pnpm run generate-tools`), writing
  `services/mcp/schema/cli-manifest.json` (`{ version, tools }`, **349 tools**).
- Captures every request-shaping transform as data: path/query/body buckets, `string-int` casts,
  `rename_params`, `soft_delete`, `inject_body`, `fallbacks`, and the query-wrapper `kind` +
  actors `source_kind_map`.

### 2. The actors transform, done faithfully

The one transform not derivable from config is actors-query shaping (it lives in
`client.ts` `runActorsQuery`). Both actors tools share `kind: "InsightActorsQuery"` — the
trends-vs-lifecycle distinction is `query.source.kind` **at runtime**. The manifest carries a
`source_kind_map` ({TrendsQuery, LifecycleQuery} → select/orderBy/limit) mirroring `client.ts`,
and the interpreter dispatches on `params.source.kind`. (This is exactly the case the prior
draft PR 53345 got wrong.)

### 3. Rust interpreter on the generated manifest

- `cli/src/agent/manifest.rs` embeds the generated `cli-manifest.json` via `include_str!`
  (single source of truth, no vendored copy).
- `cli/src/agent/interpreter.rs` is a generic interpreter handling all transform primitives.
- `cli/src/agent/command.rs` — `posthog-cli exp agent list|run [--dry-run]` exercises it end to end.

### 4. Live conformance harness (the parity guarantee)

- `services/mcp/scripts/generate-cli-conformance.ts` (`pnpm run generate-cli-conformance`) drives
  the **real generated MCP handlers** for a corpus and captures the exact request each builds,
  writing `services/mcp/schema/cli-conformance-goldens.json`.
- `cli/src/agent/interpreter.rs::live_conformance_against_mcp_goldens` asserts the Rust interpreter
  produces byte-identical requests from the same params + the manifest.
- **16 Rust tests pass**, including the live conformance test over 5 feature-flag tools (REST CRUD,
  soft-delete, query+casts, path+cast, path+body) plus code-derived tests for query wrappers, both
  actors variants, rename, and inject_body.

## What the live harness found, and how it was fixed (param defaults)

Driving the real handler for `external-data-sources-create` revealed its body includes
`"access_method": "warehouse"` — a **zod `.default()`** applied during schema parse. The interpreter
builds from raw params, so it would omit it. The harness caught this before it could ship.

**Fixed.** The generator now extracts top-level OpenAPI body-field defaults
(`extractBodyDefaults`) into the manifest, and the interpreter applies a body field's default when
the caller omits it. `external-data-sources-create` is back in the green corpus and matches.

The fix surfaced a second, subtler truth the harness also pinned down: **`param_overrides.default`
is NOT live.** It is emitted as `.default(x).optional()`, and zod's `.optional()` short-circuits
`undefined` before the default runs — so the MCP omits it for absent input. The `activity-log-list`
golden (whose `page_size` has `default: 10`) comes back with an empty query, proving it. So the
generator captures **only** OpenAPI body defaults, never `param_overrides` defaults — and
`activity-log-list` is now a permanent regression guard for that distinction.

## Known gaps / follow-ups (in priority order)

1. **Nested defaults** — only top-level body-field defaults are captured. A default nested inside an
   object-typed body field would still diverge; the harness will flag any such tool. (Top-level
   defaults — the evidenced case — are done; `param_overrides`/query defaults are intentionally not
   applied, see above.)
2. **Live capture for query/actors** — the conformance generator can't `import` `client.ts` under
   `tsx` (it depends on the Cloudflare Workers runtime). Query/actors are currently covered by
   code-derived Rust tests + `tests/unit/query-wrapper-factory.test.ts`. A true end-to-end capture
   needs the workers vitest pool.
3. **Org-scoped resolution** — `organization-get` carries `fallbacks: { id: orgId }`; the CLI is
   project-scoped (O5) and currently requires org ids to be passed explicitly.
4. **CI wiring** — add a job that runs `generate-tools` + `generate-cli-conformance`, fails on
   `git diff` (staleness), and runs `cargo test -p posthog-cli agent::`. Not added here (CI workflow
   changes are sensitive; every job needs `timeout-minutes`). Commands are ready to wire.

## Files

- `services/mcp/scripts/generate-cli-manifest.ts` (new)
- `services/mcp/scripts/generate-cli-conformance.ts` (new)
- `services/mcp/scripts/generate-tools.ts` (hook + path const)
- `services/mcp/package.json` (`generate-cli-conformance` script)
- `services/mcp/schema/cli-manifest.json` (generated, committed)
- `services/mcp/schema/cli-conformance-goldens.json` (generated, committed)
- `cli/src/agent/{mod,manifest,interpreter,command}.rs`
- `cli/src/{lib,commands}.rs` (wire `exp agent`)

> Note: `cli-manifest.json` and the goldens here were generated from a local (May-13) `openapi.json`
> snapshot. CI regenerates both from a fresh schema; the staleness check (follow-up 4) enforces it.
