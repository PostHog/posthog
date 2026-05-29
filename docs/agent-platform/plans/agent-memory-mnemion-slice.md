# Design — agent memory: the Mnemion-adapted implementation slice

> **Companion to [`agent-memory.md`](agent-memory.md).** That doc is the
> design _space_ — the requirements and the per-dimension options/agenda.
> This doc is the _decided, implemented_ slice: a concrete design adapted from
> Mnemion, already wired into the runner behind the `@posthog/memory-*` tools.
> Where the two diverge, treat `agent-memory.md` as the canonical design intent
> and this as "what shipped first" — they should be reconciled.

**Status:** v0 slice built; blueprint for the rest.
**Owner:** unassigned (Danilo / W2 capability spine).
**Tracking:** the `agent_memory` carve-out named in
[`resumable-conversations.md`](resumable-conversations.md) ("Out of scope —
cross-session memory … would need a new `agent_memory` table + ingestion
path").
**Prior art:** [github.com/daniloc/mnemion](https://github.com/daniloc/mnemion) —
a working single-tenant persistent-memory MCP server this plan adapts.
**Shape:** a **module inside the shared library** at
`services/agent-shared/src/memory/` — agent-shared is **a library, not a
deployable service**. It is **not** a separate deployable service and **not**
its own MCP server. The runner (`services/agent-runner`) wires its tools into
the agent loop; the store and per-pattern allowlist are shared, team-scoped
infrastructure living in agent-shared.

## Problem

Every agent session starts cold.
`agent_session.conversation` JSONB is the only persisted memory, and it is
scoped to one session id — the runner reads and writes it per turn, and it
dies (or is purged) with the session.
Two gaps fall out of that:

1. **Cross-session recall.** A `chat` agent that helped a user yesterday, a
   `cron` agent that ran this morning, and a `slack` mention this afternoon
   share nothing across the session boundary.
2. **Cross-agent recall.** Distinct agents on a team that should collaborate —
   a triager and a resolver, a researcher and a writer — have no shared pool of
   "what we've learned." This is the axis that matters most here.

The working assumption (see §8): memory is largely **the agent recording its
own knowledge** — learned conventions, domain facts, working notes — not facts
about third-party end-users. End-user memory is explicitly deferred.

`resumable-conversations.md` (C.4) solves a _different_ problem — replaying one
session's **audit log** from ClickHouse for display/debug (linear transcript
loading). This plan is the **semantic recall** path. The two are complementary
and must not be conflated.

## Prior art: Mnemion as the blueprint

Mnemion implements persistent, evolving memory for AI agents, exposed as an MCP
server, governed by **"data is destiny: store truth once, derive its
consequences"** — the same principle we hold the runtime queue schema to. We
adopt its _model_ and its `prime` recall wholesale, and we **drop** the parts
that exist to serve a single human across surfaces (master-secret/passkey auth,
OAuth-DCR, cross-hive federation, web-fetch adapters). What we keep is the data
model and auto-associative recall; what we add is multi-tenant scoping and
**cross-agent sharing**.

### Mnemion's model, in one table

| Mnemion term | Meaning                                      | Platform translation                                        |
| ------------ | -------------------------------------------- | ----------------------------------------------------------- |
| **Hive**     | the whole store, one per user                | **memory store** — one per team; access is per-pattern (§3) |
| **Pattern**  | an organizing structure (a table)            | kept verbatim; the unit of cross-agent access control (§3)  |
| **Entry**    | an instance within a pattern (a row)         | kept verbatim                                               |
| **Facet**    | a typed dimension of an entry (a column)     | kept verbatim                                               |
| **Link**     | a typed connection between entries           | kept verbatim                                               |
| **`prime`**  | auto-associative recall via embeddings + KNN | the headline — §5                                           |

We keep Mnemion's biological vocabulary _inside the memory subsystem_ (it is a
good, self-contained agent-facing lingua franca) and wire its edges to the
platform's: `team_id`, `agent_application`, `agent_session`, `spec`, and the
runner — which surfaces the module's tools into the agent loop in-process (§1),
no service-to-service hop.

## 1. Shape: a module in agent-shared, surfaced by the runner

Three surfaces were on the table; this is why memory lives in agent-shared and
is wired into the agent loop by the runner:

- **Not the core PostHog MCP.** That surface is for human operators and general
  agents doing analytics/authoring. Memory recall and schema evolution are
  agent-loop concerns — folding them in bloats every operator's tool catalog
  and forces a session-scoped surface through the human-OAuth/PAT codegen
  pipeline. Wrong audience.
- **Not a separate deployable MCP service.** Standing memory up as its own
  service was reconsidered: it adds a second deployable, a second DB, and a
  second trust root for what is fundamentally an agent-loop capability. The
  engine and the store belong next to the rest of the runtime, not behind a
  network boundary the runner must call out to.
- **A module in agent-shared** (`services/agent-shared/src/memory/`), whose
  tools the runner surfaces into the loop. agent-shared is a library, not a
  service, so the memory engine ships in-process. The runner only _surfaces_
  the tools; the engine and the team store are shared.

Cross-agent sharing stays safe precisely because the store and the per-pattern
allowlist are **shared, team-scoped infrastructure living in agent-shared** —
one team store, server-enforced grants — not per-agent reimplemented logic. The
runner surfaces the tools into each session, but it does not own the policy or
the data: those live in the shared module, so every agent sees the same store
and the same allowlist checks. Sharing is enforced where the store is, not in
any one agent's loop.

**Cross-surface access is explicitly not a goal.** No external Claude Code /
Claude.ai client reaches these stores. The only consumer is the PostHog runner,
on behalf of a running agent session — which keeps auth trivial (§7).

## 2. Storage substrate

Memory is runtime-written and high-churn. It lives in **agent-shared**, backed
by the existing **`agent_runtime_queue` Postgres DB** that already holds the
session queue — no new database, no new deployable. The infra fork from
Mnemion:

| Concern          | Mnemion (Cloudflare)                   | agent-shared memory module                                                                                                                |
| ---------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Store engine     | Durable Object SQLite, one DO per hive | `agent_runtime_queue` Postgres, row-level scoping                                                                                         |
| Isolation        | DO instance boundary                   | `team_id` column + fail-closed manager (§3)                                                                                               |
| Schema slice     | per-pattern real tables                | **v0: one `agent_memory_entry` table, JSONB rows** — see below                                                                            |
| Ranking / recall | Vectorize KNN over embeddings          | **v0: `Recaller` interface, FTS stand-in** (§5); no pgvector yet                                                                          |
| Embeddings       | Workers AI `bge-base-en-v1.5`          | **v0: none** — FTS stand-in has no embed source; a gateway/hosted embed impl is the future swap behind the same `Recaller` interface (§5) |
| PITR revert      | DO point-in-time restore               | no free equivalent — §Open questions                                                                                                      |

**v0 storage slice.** Entries are stored as JSONB rows in a single
`agent_memory_entry` table rather than Mnemion's per-pattern real tables. This
is a deliberate slice simplification to avoid dynamic DDL on every pattern
creation; the production graduation adopts real per-pattern tables. The pattern,
facet, and link model (§9) is preserved logically inside the JSONB shape.

Per-hive DO isolation becomes per-row `team_id` scoping — non-negotiable: every
tenant-data row carries `team_id` and starts on a fail-closed manager
(`posthog/models/scoping/README.md`, CI-enforced).

## 3. Scoping & cross-agent sharing

**One store per team**, identified by `team_id`. `team_id` is the hard tenancy
boundary — a store is **never** reachable across teams. There is no per-agent
store and no store-kind distinction: every pattern lives in the team store, and
**access is per-pattern**.

Each pattern carries an allowlist — the single mechanism that scopes _which
agents_ may touch it:

```text
team 42, pattern "incidents"
  allow:
    - { application: "triager",  access: "write" }
    - { application: "resolver", access: "read"  }
```

- **"Private" is the degenerate case** — a pattern allowlisted only to its
  creating agent (`{ creator: write }`), which is the **default** for any newly
  created pattern. An agent's private scratchpad is just patterns no other agent
  is on; no separate storage, no opt-in.
- **"Shared" is a pattern allowlisted to several agents.** A pattern can start
  private and later widen to shared without migrating data — same rows, you just
  edit the allowlist.

Granularity is the **pattern**: agents share `incidents` without exposing
`research-notes`. For now "which agents can share" = an allowlist of
**application ids/slugs within the team**, each `read` or `write` — no roles,
no RBAC, deliberately light. (A future "agent group/type" tag an allowlist can
reference instead of enumerating apps is a later refinement; noted, not built.)

**Gating keys off the allowlist shape, not a store kind** (§4). Creating or
editing a pattern allowlisted only to its creator is ungated — it affects only
that agent. The moment a change widens a pattern to _another_ agent, it runs
**approval-gated** (B.2): a team admin signs off on exposing one agent's memory
to another. That is who "controls the allowlist"; no separate ownership concept
needed. Sharing widens reach _within_ a tenant; it never crosses `team_id`.

## 4. The agent surface

The memory module exposes Mnemion's tools, which the **runner wires into each
session** as loop tools, scoped to that session's team. An agent automatically sees every
pattern in the team store its application is allowlisted on — which includes its
own creator-only ("private") patterns. No per-store opt-in (§6).

| Tool             | Mnemion equivalent                | Notes                                                                                                                          |
| ---------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `memory-prime`   | `prime`                           | §5. Auto-associative recall; the universal onramp.                                                                             |
| `memory-mutate`  | `mutate`                          | create / update / patch / archive; batchable; optimistic-locked.                                                               |
| `memory-query`   | `query`                           | filtered, sorted, paginated single-pattern reads.                                                                              |
| `memory-search`  | `search`                          | cross-pattern FTS fallback.                                                                                                    |
| `memory-resolve` | `resolve`                         | read by URI. **Web-fetch + cross-hive federation dropped** (§9).                                                               |
| `memory-evolve`  | `propose_change` / `apply_change` | create/reshape patterns **and set pattern allowlists**; approval-gated only when a change widens a pattern beyond its creator. |

Schema evolution that touches only creator-only patterns is ungated (it affects
only that agent). Evolution that widens a pattern to another agent — or edits an
already-shared pattern's allowlist — is approval-gated (§3). Authoring-time
seeding (§6) is exempt; it runs under the human author.

## 5. `prime` — the ingestion + recall path

Lifted from Mnemion's `prime.ts`, with the ranker abstracted behind a swap
point. `prime` depends only on an **opaque `Recaller` interface**
(`services/agent-shared/src/memory/recaller.ts`) — it never knows whether the
ranker uses embeddings, FTS, or anything else.

**v0 ships `FullTextRecaller`** (its `kind` is `"fts-v0"`): an in-memory tf-idf
cosine over the entry's text, with **no model, no pgvector, and no external
key**. It is a full-text-search stand-in for real embeddings, good enough to
prove the recall surface end-to-end without standing up an embed dependency.

- **Write path.** On every `memory-mutate`, the entry's text/select facets are
  recorded as the entry's recallable text. v0 has no embed call and no vector to
  upsert — the `Recaller` derives its tf-idf index from stored text. Archive
  removes the entry from the recall set.
- **Read path.** The `Recaller` ranks the agent's stated focus against the
  agent's **reachable set** (every pattern in the team store it's allowlisted to
  read — creator-only and shared alike), resolves hits to full entries, and
  expands one hop along links (schema FK refs + the bidirectional `_links` m2m).
  One adopted fix over Mnemion: **over-fetch then filter** (`min(limit·3, 50)`,
  slice after filtering) so kernel-pattern noise can't starve real hits.
- **Observability.** `prime`'s response reports the ranker `kind` (`"fts-v0"`
  today), so a consumer can tell which ranker served a recall.

**The swap point is the `Recaller` interface.** A future embedding-backed ranker
— precompute vectors on write, KNN over them — implements the same interface and
drops in with **zero change to `prime` or the tool surface**. Only the
`Recaller` impl (and §2's storage row) changes; the response's `kind` field
flips to identify the new ranker. Real embeddings are roadmapped ~2 weeks out,
targeting **2026-06-12**.

**Derive, don't store:** retrieval counts, long-term promotion, labels, and
previews are computed at read time — never stored counters. (Mnemion's
`_fragment_access_log` → `_long_term_fragments` promotion is `COUNT(*)`-derived;
kept.)

## 6. Spec surface

A small `spec.memory` block, validated at freeze time through the dual-schema
convention (zod in `agent-shared/src/spec/spec.ts`, mirrored in
`spec_schema.py`, drift-tested):

```ts
memory: z.object({
  enabled: z.boolean().default(false),
  prime_on_start: z.boolean().default(true),
}).optional()
```

That's the whole spec surface. There is no store list — there is one team store
and an agent's reach is **server-enforced** from the per-pattern allowlist (§3),
not declared in spec. Pattern creation and allowlisting happen through
`memory-evolve` / authoring, not the spec. `prime_on_start` makes "every session
starts cold"
disappear by default — the runner front-loads a `prime` over the incoming
trigger payload and injects the constellation into the framework preamble
(composes with `framework-system-prompt.md`).

## 7. Auth

Trivial by design, because cross-surface access is not a goal (§1). The runner
holds a resolved `(team_id, application_id, principal)` per session and calls
the in-process memory module with that scope; because the module is shared
library code in agent-shared, not a separate service, there is no network hop
and no service-to-service handshake to authenticate. The module enforces the
scope the runner asserts, the same trust the runner already extends to the rest
of agent-shared. There is **no second trust root, no per-store credential, no
human OAuth path.**
Authorization is two checks: the session's `team_id` owns the store, and the
session's `application_id` appears in the target pattern's allowlist with
sufficient grant (a creator-only pattern allowlists exactly its author).

## 8. Person data & deferral of end-user memory

The working assumption for v0/v1 is **agent-authored memory**: the agent's own
domain knowledge, conventions, and working notes. We are **deferring** the hard
case — an agent remembering third-party end-users (the people who talk to a
public `slack`/`chat` agent). That case carries consent, retention, and
cross-store-deletion requirements that deserve their own plan, and folding it in
now would stall the useful 80%.

Guardrails we keep regardless, so deferral doesn't become a liability:

- **Never key memory on person tables via the ORM.** Any person linkage goes
  through the **personhog client** (CLAUDE.md rule). Prefer the agent's own
  opaque principal id over PostHog person ids.
- **No third-party PII in shared patterns** for now — shared memory is for the
  fleet's own knowledge, not user dossiers. (Re-examined when end-user memory
  gets its own plan.)
- **Activity-log every mutation** (B.1 cross-cut).
- Memory crossing a Temporal activity boundary goes **by reference**, never by
  value — the ~2 MiB cap applies.

## 9. What we keep / adapt / drop from Mnemion

| Mnemion feature                                                  | Disposition                                                                                                                                                             |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| pattern / entry / facet / link model                             | **Keep** verbatim — the core.                                                                                                                                           |
| `prime` recall + one-hop links                                   | **Keep** the recall surface (with the over-fetch fix, §5); v0 ranks via the FTS `Recaller` stand-in, embed-on-write + KNN is the future swap behind the same interface. |
| "data is destiny" — derived counts/labels, refs-not-denormalized | **Keep** — already our principle.                                                                                                                                       |
| optimistic locking, patch-in-place, batch ≤100, 1 MB entry cap   | **Keep** — port as-is from `data.ts`.                                                                                                                                   |
| `propose_change` / `apply_change` schema evolution               | **Adapt** — `memory-evolve`; approval-gated on the shared store (§3/§4).                                                                                                |
| single `user:owner` hive                                         | **Replace** with one store per team; per-pattern allowlist; "private" = creator-only pattern (§3).                                                                      |
| master secret / passkey / OAuth-DCR / `_access_tokens`           | **Drop** — in-process module + runner-asserted session scope, no network hop (§7).                                                                                      |
| Durable Object SQLite + Vectorize                                | **Replace** with the `agent_runtime_queue` Postgres (v0: JSONB rows + FTS `Recaller`; pgvector is the future swap, §2).                                                 |
| cross-hive federation, web-resolve adapters, `_web_cache`        | **Drop** — cross-surface is not a goal.                                                                                                                                 |
| DO point-in-time revert                                          | **Open question** — no free PG equivalent.                                                                                                                              |
| Svelte canvas / HiveMap / LinkMap UI                             | **Out of scope** — the agent console (E.1) is the human surface.                                                                                                        |

## 10. Rollout

- **v0 — module + recall. ✅ Built.** A working slice exists at
  `services/agent-shared/src/memory/` (`schema.ts`, `recaller.ts`, `memory.ts`,
  `demo.ts`) plus tests, proven end-to-end against the `agent_runtime_queue` DB:
  the one team store (JSONB `agent_memory_entry` rows, `team_id`, fail-closed
  manager), the per-pattern allowlist (creator-only default, widened by a grant
  = the cross-agent share), `prime` recall via the `FullTextRecaller` stand-in,
  one-hop link expansion, and cross-team isolation. The tools are being wired
  into the runner now (runner-asserted session scope + activity-log integration
  follow).
  Delivers cross-_session_ recall for a single agent.
- **v1 — per-pattern allowlist + cross-agent sharing.** `memory-evolve` to
  widen a pattern's allowlist, approval-gated when it crosses to another agent
  (B.2); `prime`/query span the agent's full reachable set. The headline
  cross-agent capability.
- **v2 — prime-on-start + authoring seed.** `prime_on_start` injection; the
  authoring flow (D.1) seeds patterns at create time.
- **v3 — human surface.** Memory browser in the agent console (E.1), reusing
  Mnemion's SchemaViewer/LinkMap concepts as read views over a REST surface.

## Open questions

1. **Revert.** Mnemion leans on DO PITR. Postgres has none per-store. Lean:
   explicit inverse-migration log for schema; soft-delete + audit for data.
2. **Embedding model + cost.** v0 sidesteps this entirely — the FTS `Recaller`
   stand-in has no model and no per-write cost. The near-term plan (targeting
   ~2026-06-12) swaps in an embedding-backed `Recaller` behind the same
   interface (§5); the open part is _which_ gateway model and whether the
   embed-on-write call counts against the agent's budget (B.3). Decide before
   the swap, not before v0.

## Out of scope

- **End-user memory** — remembering third-party users with consent/retention
  guarantees. Deferred to its own plan (§8).
- **Cross-surface / external-client access** — the runner is the only consumer.
- Cross-**team** sharing — forbidden by tenancy.
- Web-URL resolve adapters and `_web_cache`.
- The spatial canvas / graph-visualization UIs.
- Replacing `resumable-conversations.md` — that is the audit-log read path.

## What this unblocks

- The cross-session memory bullet `resumable-conversations.md` punted on.
- **Collaborating agents** — a triager/resolver, researcher/writer, or any team
  fleet that pools what it learns, via shared patterns.
- Agents that get materially better the more they are used, without the operator
  hand-feeding context each session.
- A substrate the self-healing (D.2) and authoring (D.1) flows can read for
  "what has this team's fleet already learned."

## Roadmap placement

Capability extension, **layer C**, as a **module in agent-shared**
(`services/agent-shared/src/memory/`) plus **runner wiring**
(`services/agent-runner`) — not a new deployable service. Depends on **A**
(session state machine + `spec` freeze validation), **B.1** (activity-log +
principal model — the scope key), and **B.2** (approval-gated tools, for
shared-store schema evolution). Distinct from **C.4 resumable-conversations**
(audit-log replay ≠ semantic recall). Suggest slotting as **C.9** and adding a
`_TODO.md` bullet; not wired into `_ROADMAP.md` until reviewed.
