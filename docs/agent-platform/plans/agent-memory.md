# Design — persistent agent memory

**Status:** draft, options-mode (each design dimension below
presents a menu — second round picks one per dimension).
**Owner:** ben. **Tracking:** new plan, surfaced by
[`_APP_IDEAS.md`](_APP_IDEAS.md) cross-cutting gap §1.

> Today the only persistence an agent has is
> `agent_session.conversation` JSONB — bounded by the session
> lifecycle, evictable, opaque. 10 of the 13 candidate apps in
> [`_APP_IDEAS.md`](_APP_IDEAS.md) want a **cross-session**
> store keyed by `(agent, scope)` to remember outcomes,
> ground responses against curated knowledge, dedupe
> features by canonical name, recall what an individual user
> usually means, etc. This plan designs that primitive.

## 1. Problem

The use cases this primitive needs to cover, in priority order:

| Use case                                | Where it shows up                                                               | Read shape                  | Write shape                          |
| --------------------------------------- | ------------------------------------------------------------------------------- | --------------------------- | ------------------------------------ |
| Agent remembers prior outcomes          | SRE bot ("alert signature X → root cause Y")                                    | exact-key by signature      | append per resolved incident         |
| Internal knowledge base                 | AI docs ("we said X, you said Y, the doc is wrong")                             | fuzzy lookup over topics    | gated write by org-member approval   |
| Per-user context                        | AI docs, user interviewing ("Ben usually means the Node SDK")                   | key per `(user, topic)`     | last-write-wins or accumulating list |
| Cross-session dedup of fuzzy references | Feature prioritization ("`event capture` and `client SDK ingest` are the same") | semantic neighbour search   | canonical-form write + alias linking |
| Periodic rollups                        | Marketing changelog, growth review summaries                                    | list-by-prefix per week     | append weekly snapshot               |
| Stateful reconciliation                 | Financial reconciliation, Warpstream forecasting                                | last-known-state per entity | overwrite per pass                   |
| Curated ground truth                    | Competitive pricing (RFCs), reconciliation policy                               | exact-key or full-corpus    | rare, author/admin-only              |
| Shared corpus across agents             | Gap analysis ↔ customer research                                                | exact + fuzzy               | one agent writes, others read        |

What this is **not**:

- Conversation history within a session — that's
  `agent_session.conversation` JSONB +
  [`resumable-conversations.md`](resumable-conversations.md).
- Cross-region replication or multi-tenant federation —
  defer until the v1 shape is settled.
- A general-purpose vector DB for customer data — this is the
  agent's working memory, not a feature offered to PostHog
  end-users.
- A replacement for the agent bundle (`agent.md`, skills,
  prompts) — that's authoring-time content, frozen per
  revision. Memory is runtime-mutable.

## 2. Shape at a glance

A loose sketch the design dimensions in §3 either confirm or
refine.

```text
                spec.tools[]
                ├─ '@posthog/memory/recall'
                ├─ '@posthog/memory/write'
                ├─ '@posthog/memory/list'
                └─ '@posthog/memory/delete'
                                │
                                ▼
                ┌──────────────────────────────────────┐
                │  agent_memory  (table in queue PG)   │
                │ ──────────────                       │
                │  team_id    bigint                   │
                │  agent_id   uuid                     │
                │  scope      text   -- agent|user|... │
                │  scope_key  text   -- principal id…  │
                │  key        text                     │
                │  value      jsonb                    │
                │  tags       text[]   (optional)      │
                │  created_at timestamptz              │
                │  updated_at timestamptz              │
                │  ttl_at     timestamptz   (nullable) │
                │  ─                                   │
                │  PRIMARY KEY (team_id, agent_id,     │
                │               scope, scope_key, key) │
                │  INDEX on tags GIN                   │
                └──────────────────────────────────────┘
```

(Question §3.1 picks the row shape; §3.3 picks the backing
store; §3.5 decides if a parallel embeddings table joins it.)

## 3. Design dimensions

Each numbered section is a **decision to make**, not a
recommendation. The lean at the end of each is mine — the
second-round conversation picks per dimension.

### 3.1 Storage row shape

Trade-off: how structured is the per-memory row?

**Options:**

- **A. Pure KV.** `(scope, scope_key, key) → value (jsonb)`.
  Lookups by exact key only. Cheapest schema; everything
  structural the agent wants goes inside `value`.
- **B. KV + tags.** As A plus a `tags text[]` column with a GIN
  index. Lets the model recall "all memories tagged `alert` for
  this agent" without scanning. Roughly free.
- **C. Structured record.** As B plus `created_at`, `updated_at`,
  `ttl_at`, `importance int` (optional). Closer to a real record
  store; supports eviction policies (§3.6) natively.
- **D. Document store.** Values are large opaque blobs; we ship a
  JSONPath-style query language over them. Overkill for v0.
- **E. Hybrid storage + embeddings.** As C, plus a sibling
  `agent_memory_embeddings` table referencing back. Defers the
  vector decision to §3.5 but reserves the shape now.

**Trade-offs:** B is free over A. C is the natural floor once
TTL exists. D is a different product. E couples §3.1 to §3.5 —
fine if we want vector search v0, premature otherwise.

**Lean:** **C**. Tags + timestamps + TTL is the minimum forward-
compatible shape; adding columns later is a migration whereas
removing them is invisible.

### 3.2 Scope model

Trade-off: how granularly do we partition the memory namespace,
and how rigidly?

**Options:**

- **A. Minimal fixed set.** `agent` (shared across all sessions of
  this agent) + `user:<principal_id>` (per-end-user) + `session`
  (typed alias for what `conversation` JSONB does today).
- **B. + `team` scope.** Cross-agent within one customer team —
  the "shared corpus" use case (gap analysis ↔ customer
  research).
- **C. + `app` / sub-scope.** Within one agent, partition by
  purpose ("alerts" vs "runbooks" memory for the SRE bot).
  Authors define their own sub-scopes; akin to a "namespace
  inside the agent scope".
- **D. Free-form namespaces.** `scope: '<any string>'`. ACL
  applied at write time. Max flexibility, max footgun.
- **E. Hierarchical with inheritance.** `team > agent > session` —
  `recall(scope: 'agent', key)` falls back to `team` if
  not found. Powerful but the model has to understand the
  resolution order, which is its own teaching problem.

**Trade-offs:** A is the safe minimum. B unlocks one real cross-
app pattern with minimal cost. C is easy to add later as a
substring on the `key` ("alerts:<signature>") — doesn't need
schema. D + E both push complexity onto the model and the ACL
layer.

**Lean:** **B** — fixed `agent` + `user:<id>` + `team` +
`session`. Future namespacing within a scope happens via key
prefixes, not schema.

### 3.3 Backing store

Trade-off: where do the rows live?

**Options:**

- **A. Reuse the queue Postgres.** Where `agent_session`,
  `agent_revision`, `agent_pending_approval` already live. No new
  infra. Composes with the existing migrations pipeline
  ([`@posthog/agent-migrations`](../../../services/agent-migrations/)).
- **B. New Postgres database dedicated to memory.** Decouples
  scaling; the queue DB stays a queue. More ops surface.
- **C. Redis.** Fast KV but JSONB ergonomics and durability are
  worse; tags + secondary indexes need extra structures.
- **D. ClickHouse.** Append-only friendly, cheap for write-heavy
  recall logs. Bad fit for upserts / mutable last-known-state.
- **E. Multi-tier.** Hot writes in Postgres; janitor archives
  cold rows past TTL to S3 / ClickHouse. Premature v0.
- **F. pgvector extension on the queue PG.** Same DB, adds the
  vector capability inline. Couples §3.3 to §3.5 the same way E
  in §3.1 does.

**Trade-offs:** A is the boring right answer for v0 unless we
expect memory to dwarf queue traffic, which is unlikely. F is
attractive if we want to land vector search alongside.

**Lean:** **A**, with **F** as the v1 add when §3.5 picks
pgvector.

### 3.4 ACL / approval integration

Trade-off: when does a memory write need human approval?

**Options:**

- **A. No platform gates.** Approval is the spec author's job —
  if a write should be gated, they wrap the `memory/write` tool
  in [approval-gated-tools.md](approval-gated-tools.md)'s
  `requires_approval: true`. Composes cleanly with existing
  machinery; nothing memory-specific.
- **B. Per-scope default policy + spec override.** Sensible
  defaults baked in (`agent` and `session` writes open; `team`
  writes approval-gated by default; `user:<id>` writes open if
  the session's principal **is** that user, else gated). Spec
  can override.
- **C. Per-row writer ACL.** Each row carries `writers:
['team_admins' | 'self' | ...]`. Granular but the model has
  to reason about who's "self" in each context.
- **D. Two-tool split.** Ship `memory/write-private`
  (no approval) and `memory/write-shared` (approval-gated by
  default). Privilege difference shows up at the tool boundary,
  not the data boundary — clearer for the model, doubles the
  tool surface.
- **E. Combination of B + D.** Defaults at the scope level _and_
  separate tools so the model can see the cost up front.

**Trade-offs:** A leaves the gates to the author — maximally
composable, requires per-agent vigilance. B is the right
"safe-by-default" floor but is invisible to the model unless we
also surface it in the tool description. D makes the privilege
visible in the model's decision space.

**Lean:** **B**. The defaults make accidental cross-tenant /
cross-user leakage hard; spec authors retain the override.
Reuses [approval-gated-tools.md](approval-gated-tools.md)
end-to-end (the per-scope default just sets the spec
`requires_approval` flag for the relevant tool ref at freeze
time).

### 3.5 Semantic / fuzzy search

Trade-off: how does the agent find a memory it doesn't know the
exact key for?

**Options:**

- **A. v0: none.** Exact key + `list_by_prefix(scope, prefix)`
  only. Apps that need fuzzy lookup load all keys for the scope
  and let the LLM dedup. Cheap, dumb, works at small N.
- **B. v0: Postgres full-text.** `tsvector` column over `value`
  serialized to text; `recall(scope, query)` runs a
  `to_tsquery` lookup. Free with Postgres, works well for "find
  memories about pricing".
- **C. v0: pgvector embeddings.** Embed every write via an
  embedding API; vector-search on recall. Higher cost (embedding
  API per write, ~$0.02 per 1M tokens) and an extra
  infrastructure surface. Unlocks fuzzy dedup from day one.
- **D. v0: tags + LIKE; v1: pgvector.** Bootstrap with tag-based
  filters + `value::text LIKE '%query%'`, layer pgvector when an
  app actually proves it needs fuzzy semantic recall.
- **E. v0: external vector store (Pinecone / Qdrant / Turbopuffer).**
  Best-of-breed retrieval; new infra dependency, harder ops story.

**Trade-offs:** A is the truthful "we haven't solved fuzzy yet"
position. B is the cheapest middle ground. C is the cleanest
shape if we know fuzzy is core. D is the pragmatic ladder. E is
v2 territory.

**Lean:** **D**. The apps that genuinely need vector search
(feature prio dedup, customer research clustering) aren't on
the end-of-month critical path; exact-key + tags + LIKE covers
the 6 buildable infants. Cost stays at zero until proven.

### 3.6 Eviction & size limits

Trade-off: how do we keep the table from growing unbounded?

**Options:**

- **A. Hard caps only.** N keys per scope, M bytes per value;
  writes past the cap fail. No TTL. Author-bears-the-load.
- **B. Per-key TTL.** Agent sets `ttl_seconds?` on write; defaults
  unbounded. Janitor sweeps expired rows. Author-driven but
  default-permissive.
- **C. Per-scope quotas + janitor sweep on TTL.** Both caps and
  TTL; when a write would exceed the quota and the agent didn't
  set a TTL, oldest unpinned row evicts (LRU).
- **D. Importance-based eviction.** Agent declares `importance`
  on write; eviction prefers low-importance. Composable with B.
- **E. No eviction in v0.** Revisit when someone hits a wall.
  Realistic for small agents but risky long-term.

**Trade-offs:** A is brittle (writes start failing under load).
B is the standard "TTL is the author's lever". C is the right
shape once any apps reach scale. D adds nuance for "permanent
memory" but the model has to use it consistently.

**Lean:** **C** without importance. Per-scope quota
(e.g. 10MB / 10k rows per agent-scope by default, configurable
in spec), per-key TTL, LRU eviction when quota exceeded. Janitor
handles cleanup on its existing sweep cadence
([`agent-janitor/src/sweep.ts`](../../../services/agent-janitor/src/sweep.ts)).

### 3.7 Tool surface (what the model sees)

Trade-off: how many tools, how granular?

**Options:**

- **A. Two-tool atomic.** `recall(scope, key)`, `write(scope,
key, value)`. Maximally minimal; everything else (list,
  delete, search) the agent simulates via key naming
  conventions.
- **B. Four-tool CRUD.** A + `list(scope, prefix?)`, `delete(scope,
key)`. The model can audit its own memory, clean stale entries.
- **C. CRUD + search.** B + `search(scope, query, limit?)` once
  §3.5 ships any flavour of fuzzy lookup. Distinct tool so the
  model knows the cost.
- **D. Bulk variants.** `write_many`, `delete_many` reduce turn
  count. Complicates ACL + quota enforcement (partial-fail
  semantics).
- **E. Unified mega-tool.** Single `memory({op: 'recall' | ...,
args: ...})`. Fewer slots in the tool list; more decision
  burden per call — model-hostile.

**Trade-offs:** A under-serves the model (no observability over
its own memory). B is the natural minimum. C composes once §3.5
lands. D and E both look like premature optimisation.

**Lean:** **B** for v0, growing to **C** when §3.5 picks
anything other than option A.

### 3.8 Value shape — typed or free-form?

Trade-off: do we constrain what an agent can store?

**Options:**

- **A. Free-form JSONB.** Author's problem if memories drift in
  shape across revisions; the model parses whatever it wrote.
- **B. Optional zod schema per scope** declared in
  `spec.memory.scopes[]`. Writes validated at the boundary;
  recalls return parsed objects. Catches drift but adds spec
  surface.
- **C. Typed-by-tag.** A schema registry keyed by tag; a row
  tagged `incident` must conform to the `incident` schema.
  Implicit binding; powerful if you also use tags for retrieval
  (§3.1).

**Trade-offs:** A is the freedom-to-fail default. B and C both
trade some flexibility for "future you can read what past you
wrote".

**Lean:** **A** for v0; pave the way for **B** by leaving room
for a `spec.memory.schemas?` field. Realistic prediction:
authors learn the hard way and ask for B by month three.

### 3.9 Concurrency / consistency

Trade-off: two sessions of the same agent write the same key —
what happens?

**Options:**

- **A. Last-write-wins.** Atomic per-row, no version checks.
  Simplest. Lost writes are possible.
- **B. Optimistic concurrency.** `write(scope, key, value,
expected_version?)`. Returns conflict on mismatch; agent
  re-reads and retries. Composes with quota.
- **C. Server-side merge for JSONB.** `write(scope, key,
patch)` with `jsonb_set` semantics. Each write is additive;
  conflict-free for non-overlapping keys.
- **D. Append-only logs.** `append(scope, key, entry)` puts a
  new row; recall returns the list. Push deduplication onto
  read.

**Trade-offs:** A is fine for single-session-per-agent
patterns (SRE bot, reconciliation). B matters for high-
concurrency apps (gateway-agent driven fan-out). C is JSON-
native but the model has to think in patches. D shifts the
mental model toward "memory is a log".

**Lean:** **A** for v0; surface a single advisory `expected_version`
return value on read so v1 can flip to **B** without a tool
contract change.

### 3.10 Revision lifecycle

Trade-off: when an agent's revision is bumped, what happens to
memory?

**Options:**

- **A. Memory persists unchanged across revisions.** It's the
  agent's accumulated knowledge, independent of code. Risk: a
  semantic change to a memory's shape silently breaks the next
  run.
- **B. Memory bound to a revision.** Each revision starts fresh;
  on promote, the author can declare an explicit "copy from
  prior" step. Safer but loses continuity.
- **C. Memory persists; revisions declare migrations.** The
  freeze step can ship a one-shot migration script that runs
  against the agent's memory before the new revision goes live.
  Most flexibility, most surface area.
- **D. Memory persists; soft-versioned values.** Each row
  carries the `min_revision_id` that wrote it; recall can filter
  out memories from older revisions if the schema changed.

**Trade-offs:** A matches operator intuition ("the agent
remembers across deploys"). B is safer but feels wrong. C is
the right shape long-term. D is a middle ground that defers C.

**Lean:** **A** for v0, **D** as the v1 hardening once we hit
the first real schema-drift incident.

### 3.11 Observability + activity log

Trade-off: are memory ops audit-logged?

**Options:**

- **A. Same as any tool call** — appears in the runner's existing
  trace + the platform-LLM-analytics `$ai_span` event per tool
  dispatch (per
  [`platform-llm-analytics.md`](platform-llm-analytics.md)).
  No memory-specific surface.
- **B. + activity log entries** for `write` / `delete` against
  `team` and `user:<id>` scopes (the privileged tiers).
  Composes with [`per-session-access-elevation.md`](per-session-access-elevation.md)
  §8 activity log integration.
- **C. + per-row write history** stored alongside the row.
  Heavy; lets a user see "what did this memory used to be?".

**Lean:** **B**. Tool-call traces cover the day-to-day; activity
log entries on the privileged tiers keep auditability without
schema bloat.

### 3.12 Cost / quotas at the team level

Trade-off: does memory have a per-team budget?

**Options:**

- **A. Free.** Storage is cheap, no quota tracking.
- **B. Per-team byte cap.** Hard cap; writes past the cap fail
  with `memory_quota_exceeded`. Composes with the per-scope
  quota in §3.6.
- **C. Per-team byte cap with grace.** Soft warning, then hard
  fail after N days.
- **D. Cost meter only.** Tracked in the team's billing surface
  but not enforced; serves as data for v1 enforcement.

**Lean:** **D** for v0 — track but don't enforce. **B** once
the data tells us where to set the cap.

## 4. Composition with existing plans

- [`approval-gated-tools.md`](approval-gated-tools.md) — the
  spec author wraps `memory/write` with `requires_approval:
true` for the gates §3.4 wants. No new approval surface.
- [`per-session-access-elevation.md`](per-session-access-elevation.md) —
  the session's principal supplies `user:<principal_id>` for
  §3.2's user scope. Read/write into `user:<their_id>` is open
  to a session running on behalf of that user; reads into
  other users' scopes require elevation.
- [`platform-llm-analytics.md`](platform-llm-analytics.md) —
  memory tool calls already appear as `$ai_span` events for
  free.
- [`resumable-conversations.md`](resumable-conversations.md) —
  the `session` scope (§3.2) is a typed alias for what that
  plan's conversation log already serves; the new memory tool
  is for the agent's working memory, not its raw turn log.
- [`agent-console-website.md`](agent-console-website.md) §6 —
  a `/agents/:slug/memory` read page lists memories by scope.
  Editing through the concierge per the rest of that plan.
- [`agent-janitor/src/sweep.ts`](../../../services/agent-janitor/src/sweep.ts) —
  TTL / quota eviction runs on the existing sweep cadence; no
  new worker.

## 5. What this unblocks (from `_APP_IDEAS.md`)

- ✅ Full SRE bot (alert-outcome memory).
- ✅ AI docs agent's "update memories" loop (internal +
  per-user tiers).
- ✅ Marketing weekly changelog rollups.
- ✅ Feature prioritization dedup (with §3.5 option C/D for
  semantic match).
- ✅ Competitive pricing RFC grounding.
- ✅ Industry intelligence per-user interests.
- ✅ Customer research cross-call clustering (with semantic
  search).
- ✅ User interview cross-respondent corpus.
- ✅ Gap analysis ↔ customer research shared corpus (with §3.2
  option B `team` scope).
- ✅ Financial recon last-known reconciliation state.
- ✅ Warpstream historical projection tracking.

## 6. Out of scope for v0

- Cross-region replication.
- Multi-tenant federation (one customer's agent reading another
  customer's memory).
- A general-purpose vector DB exposed to PostHog end-users.
- Memory-as-a-product: customers writing their own apps that
  consume an agent's memory directly via API. (Possible later
  via the existing REST surface.)

## 7. Decisions to confirm (the second-round agenda)

| §    | Question                     | Options               | Lean            |
| ---- | ---------------------------- | --------------------- | --------------- |
| 3.1  | Storage row shape            | A · B · C · D · E     | **C**           |
| 3.2  | Scope model                  | A · B · C · D · E     | **B**           |
| 3.3  | Backing store                | A · B · C · D · E · F | **A** (F at v1) |
| 3.4  | ACL / approval integration   | A · B · C · D · E     | **B**           |
| 3.5  | Semantic / fuzzy search      | A · B · C · D · E     | **D**           |
| 3.6  | Eviction & size limits       | A · B · C · D · E     | **C**           |
| 3.7  | Tool surface                 | A · B · C · D · E     | **B** → **C**   |
| 3.8  | Value shape — typed or free? | A · B · C             | **A** (B later) |
| 3.9  | Concurrency / consistency    | A · B · C · D         | **A** (B later) |
| 3.10 | Revision lifecycle           | A · B · C · D         | **A** (D later) |
| 3.11 | Observability + activity log | A · B · C             | **B**           |
| 3.12 | Team-level quota             | A · B · C · D         | **D** (B later) |

## 8. Rollout (sketch — depends on §7 picks)

**v0 — exact-key store, four-tool CRUD, no fuzzy search.** The
minimum useful primitive. Ships unblocking 6 of the 10
memory-gated apps.

**v0.1 — tags + LIKE retrieval** (if §3.5 picks **D**) — closes
the easy fuzzy use cases without infra.

**v1 — pgvector + search tool** (if §3.5 picks **D** then
ladders) — closes the dedup / clustering use cases that need
real semantic match.

**v1.5 — schema gate** (if §3.8 picks **B**) — once authors
have hit the schema-drift wall once.

**v2 — versioning + memory migrations** (if §3.10 picks **D** /
**C**) — once a memory's _semantics_ change in a real release.
