# Agentic CLI — Phase 0 Spike & Gate Result

**Verdict: GO for Rust-native.** All spike tool _requests_ — including the worst cases (query
wrappers and actors) — are reproduced byte-for-byte (at the JSON-semantic level) by a Rust
interpreter reading a declarative manifest. The only divergence is _response presentation_ for a
few tools, which is deliberately out of the request-parity contract (Decision 6: raw JSON default,
`--enrich` opt-in).

## What was built

A working Rust spike inside the existing `cli/` crate (`cli/src/agent/`):

- `spike-manifest.json` — a hand-authored declarative manifest for 7 tools, faithful to
  `products/feature_flags/mcp/tools.yaml`, the generated handlers, and `client.ts`. (Codegen
  integration is Phase 1 — see "Why hand-authored" below.)
- `manifest.rs` — manifest schema (params buckets, casts, renames, `soft_delete`, `inject_body`,
  `query_wrapper` incl. an `actors` block).
- `interpreter.rs` — the generic request-builder + 10 conformance tests.
- `command.rs` — `posthog-cli exp agent list|run` to exercise it end to end (`--dry-run` prints the
  resolved request; otherwise it sends via the existing authenticated `PHClient`).

`cargo test --lib agent::` → **10 passed**. `cargo build` → clean.

## Tools covered and the transforms they prove

| Tool                          | Transform proven                                                                                                  |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `create-feature-flag`         | POST, body field whitelist (only declared fields, present-only)                                                   |
| `update-feature-flag`         | PATCH, path param + body split                                                                                    |
| `delete-feature-flag`         | **soft_delete** → method rewrite to PATCH + `{deleted:true}`                                                      |
| `feature-flag-get-definition` | path-param substitution + `encodeURIComponent` + `string-int` cast                                                |
| `feature-flag-get-all`        | query build in handler order, `string-int` casts, skip null/empty-array, JSON-stringify non-empty arrays          |
| `query-trends`                | query-wrapper `{query:{...,kind}}` + `output_format` strip + **`filterGroup` → nested `PropertyGroupFilter`**     |
| `query-trends-actors`         | **`ActorsQuery` rewrap** (`select`/`orderBy`/`limit`) + conditional `matched_recordings` from `includeRecordings` |

The actors case is the one the prior PR (#53345) got wrong — it POSTed the raw query to `/query/`
instead of re-wrapping. The spike reproduces the real MCP request (`client.ts:1097-1196`).

## The one real divergence — and why it's acceptable

The actors tools (and `enrich_url` tools) do **response** post-processing in the MCP:
`runActorsQuery` flattens `actor` → `distinct_id/email/name`, turns `matched_recordings` into
`{baseUrl}/replay/{id}` links, and builds a `columns` array; query tools append `_posthogUrl`.

A raw-JSON CLI returns the unshaped API response instead. This is consistent with **Decision 6**
(raw JSON by default; `--enrich` opts into MCP-identical responses) and your **O1** choice. It is a
_response-shape_ difference, never a _request_ difference — the side-effecting request is identical.
The conformance contract is therefore scoped to requests, and that scope is what passed.

## Why the manifest was hand-authored (not generated yet)

The gate question was "can a Rust runtime faithfully reproduce MCP behavior from a declarative
manifest?" — a question about the _runtime + parity model_, not about codegen plumbing. Hand-authoring
a faithful slice answered it for a fraction of the cost of first wiring `generateCliManifest()` into
the 67 KB `generate-tools.ts`. Now that the answer is yes, codegen integration is the Phase 1 entry
point and the manifest schema in `manifest.rs` is the target shape.

## Limits of this gate (honest scope)

- Goldens are derived from reading the authoritative MCP source, not from executing the live MCP
  handlers. Phase 1 replaces this with a real golden-capture harness (run MCP handlers in dry-run,
  diff against the Rust builder) wired into CI — the durable drift guard from the plan.
- 7 tools, not 388. The transforms covered are the structurally hard ones; Phase 1 expands the corpus
  to sample every transform category and domain.
- `encodeURIComponent` parity is implemented to JS semantics but only exercised on numeric ids here;
  string path params with special chars need a dedicated conformance case.

## Recommended next step (Phase 1 kickoff)

1. Wire `generateCliManifest()` into `generate-tools.ts`; emit the real `cli-manifest.json` for all
   enabled tools using the schema in `manifest.rs`.
2. Build the live golden-capture conformance harness and put it in CI (manifest/generator/runtime
   changes must keep requests identical to MCP).
3. Swap the spike's `include_str!("spike-manifest.json")` for the generated manifest.
