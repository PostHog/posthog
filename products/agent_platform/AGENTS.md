# agent_platform — Django side of the v2 agent platform

This product is the **authoring + control-plane half** of the agent
platform. The runtime is in node services at `products/agent_platform/services/agent-{ingress,runner,janitor}`.
You will almost always need both sides in your head — read the
[local-dev guide](docs/local-dev.md) before
making non-trivial changes.

## What lives here

- [models.py](backend/models.py) — `AgentApplication`, `AgentApplicationRevision`.
  These are the **v2 shapes** (the file was renamed back from `models_v2.py`
  post-cutover). Both tables live in the main posthog DB and are read by
  every node service.
- [serializers.py](backend/serializers.py) / [api.py](backend/api.py) — the
  authoring REST surface (`/api/projects/<team>/agent_applications/...`).
- [janitor_client.py](backend/janitor_client.py) — thin HTTP client into the
  janitor for bundle reads/writes and the native_tools listing. **Django
  never touches the bundle filesystem directly** — always proxy through
  here. Auth is an audience-bound JWT (`aud = agent-janitor.rpc`) signed
  with the shared `AGENT_INTERNAL_SIGNING_KEY` and sent as
  `x-internal-secret`.

## Rules of engagement

1. **Anything that changes a serializer or viewset shape → rerun
   `hogli build:openapi`** before testing or pushing. The MCP tool
   surface ([services/mcp/src/tools/generated/agent_platform.ts](../../services/mcp/src/tools/generated/agent_platform.ts))
   and the frontend types ([frontend/generated/api.schemas.ts](frontend/generated/api.schemas.ts))
   both regenerate from the OpenAPI spec. Skip this and the MCP tool
   schemas silently drift.

2. **Never query the runtime tables from Django.** `agent_session`,
   `agent_user`, `agent_sandbox_instance` live in `AGENT_DB` and are
   owned by the node side. If Django needs runtime info, add a
   janitor endpoint and call it via `janitor_client`.

3. **Spec edits must round-trip through the node-side schema.** The
   `revision.spec` JSONB is validated by
   [`AgentSpecSchema`](../../products/agent_platform/services/agent-shared/src/spec/) on the
   node side; Django passes it through. If you tighten a constraint
   server-side, mirror it in the zod schema (or vice versa), otherwise
   the janitor's `/revisions/:id/validate` will start rejecting things
   Django happily wrote.

4. **Encrypted env (`AgentApplication.encrypted_env`) uses
   `ENCRYPTION_SALT_KEYS`.** The same keys must be present on the
   runner so it can decrypt at session start. Don't add a second
   encryption mechanism — extend `EncryptedTextField`'s key set.

5. **Isolation: not yet enforced.** There's no `backend/facade/` or
   `backend/presentation/` boundary yet, so no `backend:contract-check`.
   Don't add new cross-product imports into here — when isolation lands
   a facade will be the only allowed entry point.

## When you change something here

Vital changes need an e2e case in [products/agent_platform/services/agent-tests/](../../products/agent_platform/services/agent-tests/)
— the harness drives the full Django-shaped flow against in-process
ingress + runner + janitor. A change to the authoring API that doesn't
have a case will silently regress when the node side evolves. See
[agent-tests/CLAUDE.md](../../products/agent_platform/services/agent-tests/CLAUDE.md) for the
pattern.

## Reading service logs locally

In dev the node services (`agent-ingress`, `agent-runner`, `agent-janitor`) tee
their JSON logs to `/tmp/posthog-agent-logs/<service>.log` (set via
`AGENT_LOG_FILE` per service in `bin/mprocs.yaml`) in addition to the mprocs pane.
So you can read/grep them directly instead of scraping the terminal:

```bash
tail -n 200 /tmp/posthog-agent-logs/agent-runner.log
# one session across all services:
grep -h '<session_id>' /tmp/posthog-agent-logs/*.log | jq -c '{name,event,msg,err}'
```

Each line is a pino JSON record (`name` = subsystem, plus any bindings like
`session_id`). Prod logs to stdout only; tests don't write files. Wired in
`agent-shared/src/runtime/logger.ts`.

## Pointers

- **Local dev + MCP local + e2e overview** —
  [docs/local-dev.md](docs/local-dev.md).
- **Janitor HTTP surface** —
  [products/agent_platform/services/agent-janitor/src/server.ts](../../products/agent_platform/services/agent-janitor/src/server.ts).
- **Spec shape (source of truth)** —
  [products/agent_platform/services/agent-shared/src/spec/](../../products/agent_platform/services/agent-shared/src/spec/).
