# agent-ingress — Inbound HTTP for the v2 agent platform

Owns every external entry point into a running agent: chat (`/run`,
`/send`, `/listen`), webhook (`/webhook`), Slack (`/slack/events`),
MCP (`/mcp`), domain + path routing, auth, identity.

Read [docs/local-dev.md](../../docs/local-dev.md)
for the wider dev flow before non-trivial changes.

## What lives here

- [src/triggers/](src/triggers/) — one module per trigger type. Each
  resolves the principal, normalizes the input, enqueues a session.
- [src/routing/](src/routing/) — slug + domain resolution against the
  application table.
- [src/enqueue/](src/enqueue/) — the path from "validated request"
  → row in `agent_session`.
- [src/index.ts](src/index.ts) — prod bin entry. Reads env, wires
  real PG pools + `RedisSessionEventBus`, starts the listener.
- [src/lib.ts](src/lib.ts) — library entry (`buildApp`, the auth and
  event-bus types). The harness imports from here.

## Rules of engagement

1. **Ingress writes only to `agent_session` (+ `agent_user`).** It
   never touches `agent_application` / `agent_revision` except to
   read for routing. Authoring writes go through Django →
   janitor — not through here.

2. **Trigger handlers are skinny.** Look up app → resolve secrets →
   verify signature → resolve identity → enqueue → return. Anything
   heavier is a smell — long work belongs in the runner, not in the
   request thread. (Slack flipped the app-vs-signature order: we resolve
   the agent first so we know which signing secret to use.)

   **Slack signing secret is per-agent, not global.** There is no
   `SLACK_SIGNING_SECRET` env. The Slack handler looks up the
   conventional `SLACK_SIGNING_SECRET_KEY` (from
   `@posthog/agent-shared`'s `TRIGGER_REQUIRED_SECRETS` registry) in the
   agent's `AgentApplication.encrypted_env` via
   `SecretResolver`, which decrypts on every request using
   the same `EncryptedFields` helper as everywhere else. Django's
   promote action gates on the entry being present so production
   requests always find a value. BYO Slack apps work day-1. To add
   another "trigger needs a secret in encrypted_env" use case, add an
   entry to `TRIGGER_REQUIRED_SECRETS` and look it up via the resolver
   — don't add a new global env var, and don't put the key name on the
   spec.

3. **`/listen` SSE depends on the bus.** `RedisSessionEventBus` is
   the only impl (in-memory variant was deleted — it silently broke
   multi-host fan-out). Every entrypoint must wire `REDIS_URL`; the
   harness wires it against the local Redis with a per-cluster
   channel prefix so concurrent test files don't deliver each other's
   events. If you add a new lifecycle event, make sure SSE consumers
   handle it.

4. **Auth lives in `AuthProvider`, not inlined.** Don't bake principal
   lookup into a trigger handler — extend or swap the `AuthProvider`
   passed to `buildApp`.

5. **One auth mode, one trust model. Pick by the use case, not by
   convenience.** Each `AuthMode` carries a specific identity semantic;
   trying to fake another mode's semantic on top is the bug we keep
   repeating.

   | Use case                                                           | Auth mode          | Principal identity                                        |
   | ------------------------------------------------------------------ | ------------------ | --------------------------------------------------------- |
   | Single upstream integration (Stripe, GitHub, internal CRM webhook) | `shared_secret`    | One per agent — every secret holder is the same principal |
   | Embedded chat / multi-tenant with per-caller isolation             | `jwt`              | `sub` (forge-resistant; upstream signs it)                |
   | PostHog user calling their own agent                               | `posthog`          | The PostHog user (validated against `/api/users/@me/`)    |
   | PostHog backend → ingress server-to-server                         | `posthog_internal` | The platform itself                                       |
   | Genuinely public surface (docs embed, marketing)                   | `public`           | Anonymous — opt-in via `acknowledge_public_exposure`      |

   `shared_secret` accepts two possession proofs, picked by `scheme`:
   omitted/`plain` compares the header value to the secret verbatim
   (incident.io, Grafana — anything that can echo a configured header);
   `scheme: 'hmac_sha256'` expects hex `HMAC-SHA256(raw body, secret)`
   in the header (`signature_prefix` default `sha256=`) for signers that
   never transmit the secret itself — GitHub's `X-Hub-Signature-256` and
   most webhook providers. Same single-principal trust model either way.

   **`shared_secret` is single-principal by design.** Holders of the
   agent's secret share a session space; `x-external-key` is a routing
   tag, not a credential, and `principalsMatch` discriminates only on
   `team_id`. Do NOT add a per-caller header / claim / discriminator to
   this mode — anything the holder asserts behind the secret is forgeable
   by any other holder, and a "self-asserted identity" creates a false
   security boundary that looks like isolation but isn't. Per-caller
   isolation belongs in `jwt`. We tried this twice (PR 63930 added a
   spec-level `caller_id_header`; the followup refactored it to the
   conventional `x-posthog-caller-id` header) and reverted both —
   re-introducing it should require a threat-model write-up, not a
   review nit.

   This means the original threat-model finding F5 ("any holder of the
   agent's shared secret can resume any session keyed under it") is now
   the **documented model**, not a latent bug. The platform-level
   mitigation is to scope each `secret_ref` to a single upstream
   integration; multi-tenant isolation is `jwt`'s job. If a future use
   case genuinely needs continuity _with_ per-caller isolation under
   `shared_secret` (today it doesn't), the design path is
   **server-issued unguessable resume tokens** (random token returned
   on session create, required on resume), NOT a self-asserted caller
   header. Reach for that only when something concrete demands it.

6. **No `process.env` reads + one HttpClient.** Env access goes
   through `loadAgentIngressConfig` at boot; the typed `Config` flows
   from there. Every outbound HTTP call (PostHog API introspect,
   Slack identity bridge) reaches the wire via the shared `HttpClient`
   wired in `src/index.ts`. See agent-shared/CLAUDE.md rules 7-8 for
   the full story + the lint rule that enforces it.

## When you change something here

Trigger surface and routing edges have e2e cases under
[services/agent-tests/src/cases/](../../services/agent-tests/src/cases/)
(`chat-trigger`, `slack-trigger`, `webhook-mcp-trigger`,
`routing-edges`, `listen-sse`, `strict-principal`, ...). A change
without a matching case will regress silently.

## Pointers

- **Local dev + MCP local + e2e overview** —
  [docs/local-dev.md](../../docs/local-dev.md).
- **Test conventions** —
  [services/agent-tests/CLAUDE.md](../agent-tests/CLAUDE.md).
- **Shared building blocks (queue, identity store, event bus types)** —
  [services/agent-shared/](../agent-shared/).
