# agent-janitor — Authoring HTTP + sweep timer

Two unrelated responsibilities in one process:

1. **Authoring API** — bundle CRUD + freeze/validate/clone +
   `/native_tools` listing. Django proxies through here so it doesn't
   need direct filesystem access.
2. **Sweep timer** — re-queues stuck `running` sessions and fails
   stuck `waiting` sessions on a configurable interval.

Both are unauthenticated unless `AGENT_INTERNAL_SIGNING_KEY` is set (it must be in
prod). Read [docs/local-dev.md](../../docs/local-dev.md)
for the wider dev flow.

## What lives here

- [src/server.ts](src/server.ts) — the HTTP surface. Endpoints (all
  guarded by `x-internal-secret`):
  - `/revisions/:id/{manifest,file,bundle,freeze,validate,clone_from}`
  - `/native_tools` — every `@posthog/*` tool the runner knows
  - `/healthz`
- [src/sweep.ts](src/sweep.ts) — the periodic queue scrubber.
- [src/validate-spec.ts](src/validate-spec.ts) — pre-flight checks
  on a draft revision (entrypoint, tool ids, custom-tool files,
  skill paths).
- [src/index.ts](src/index.ts) — prod bin entry.
- [src/lib.ts](src/lib.ts) — library entry (`buildJanitorApp`).

## Rules of engagement

1. **Janitor is the only direct user of the bundle store.** Django
   proxies through `/revisions/*`. The runner reads bundles from the
   store directly **but only at session start** — never via janitor
   HTTP. Don't add a fourth caller.

2. **Sweep thresholds are env-tunable, not constants.**
   `STUCK_RUNNING_MS`, `STUCK_WAITING_MS`, `MAX_RETRIES`,
   `SWEEP_INTERVAL_MS` — keep new sweep behavior on the same env
   pattern so prod tuning stays declarative.

3. **`/native_tools` reflects what `@posthog/agent-tools` exports
   right now.** If you add a new native tool, it'll show up here
   automatically — but the authoring AI's view of "available tools"
   comes from this endpoint. Don't filter it server-side; that's the
   authoring UI's job.

4. **Validate runs server-side too.** Anything the janitor accepts on
   freeze must be acceptable to the runner at session start. If you
   tighten the spec on the runner side, mirror it in
   `validate-spec.ts`, otherwise the runner will reject sessions for
   revisions the janitor already froze.

5. **No `process.env` reads + one HttpClient.** Env access goes
   through `loadAgentJanitorConfig` at boot; the typed `Config` flows
   from there. Any outbound HTTP added later must go through the
   shared `HttpClient` (none today since reaper uses the Modal SDK).
   See agent-shared/CLAUDE.md rules 7-8 for the full story + the
   lint rule that enforces it.

## When you change something here

Authoring + sweep e2e behavior is covered in
[services/agent-tests/src/cases/janitor.test.ts](../../services/agent-tests/src/cases/janitor.test.ts).
The local unit tests ([server.test.ts](src/server.test.ts),
[sweep.test.ts](src/sweep.test.ts), [validate-spec.test.ts](src/validate-spec.test.ts))
cover HTTP shape + threshold math but not the cross-service flow.

## Pointers

- **Local dev + MCP local + e2e overview** —
  [docs/local-dev.md](../../docs/local-dev.md).
- **Django proxy client** —
  [products/agent_platform/backend/janitor_client.py](../../products/agent_platform/backend/janitor_client.py).
- **Test conventions** —
  [services/agent-tests/CLAUDE.md](../agent-tests/CLAUDE.md).
