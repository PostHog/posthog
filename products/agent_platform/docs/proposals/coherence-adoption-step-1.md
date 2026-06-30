# Adopting Coherence in the agent platform — a first step

> Proposal. Not yet implemented. Imports the "Coherence" doctrine from
> [daniloc/mnemion](https://github.com/daniloc/mnemion) and applies it to this
> subsystem. Authored from a code + git-history review of both projects.

## 1. What Coherence is (in one breath)

> A recurring bug is a *structural question answered at call sites*. Convert it:
> **one declarative home** (data, not convention) → **derive** every gate from it →
> **enforce at the chokepoint** all paths cross → **fail closed** → **assert
> totality** so the absence of holes is *checked, not hoped* → make the boundary
> **un-routable in the type system**, not just documented.

The operative grammar is a **graded enforcement ladder** — match rigor to consequence,
push boundaries *up* the ladder, but don't over-enshrine (that is its own
inner-platform pathology):

| tier | name | guarantee | how |
| --- | --- | --- | --- |
| 1 | **enshrined** | the unsafe state is *unrepresentable* | type/capability split, frozen-immutable, born-hashed |
| 2 | **totality-checked** | an *oracle* proves the N sites agree, fails loud on any unclassified member | a test that enumerates a domain |
| 3 | **convention** | held by memory / a doc | (the state we want to *leave*) |

A **totality oracle** is the linchpin: it converts the unanswerable block-list
question *"did we find every sink?"* into the checkable one *"does the single
declaration cover the enumerable domain, and fail the build if not?"*

The portability thesis: this becomes a property of the *framework*, not of
disciplined agents, only when the convergent move (add a row to the one registry)
is made **cheaper** than the divergent move (add a guard at the new call site).

## 2. Why this subsystem is a candidate (the evidence)

The doctrine's diagnostic tell is *"fix-one-open-another"* — a class of fix
recurring at call sites instead of a boundary. The agent platform shows it on
two boundaries:

**The approval / act-as-the-user gate** (trust raised from agent input to owner
authority):

- `bd1f7fa` per-principal identity, credentials + approvals authority
- `78f7a0ad` "stop session_principal approval gate from **auto-dispatching**"
- PR #66007 leaves **client tools with no approval field** — a present hole: the
  gate is resolved *per lane* (native/custom carry `approval_policy` on their ref;
  MCP via effective level; client → nothing), which is a block-list, not a chokepoint.

**The MCP credential / authorization path:**

- `ec9e281` "**remove** the auth.integration MCP credential path" (a path deleted
  because it was a fourth way through a boundary that should have one)
- PR #66007 reworks the whole credential model and ships a 6-item *"known gaps"*
  list — including **gap #6, a real IDOR**: `PgMcpConnectionStore.resolve`
  authorizes a shared `connection` by `(installation_id, team_id)`, but
  `MCPServerInstallation` is *user*-scoped, so an editor who knows a teammate's
  installation UUID can use their stored bearer. This is the doctrine's
  consent-gate bug exactly: *the chokepoint enforces at the convenient layer
  (team) instead of the layer the invariant is about (the credential's owner).*

Two corroborating signals:

- **The platform already has coherent boundaries** — proof the shape fits:
  `runSession` is **fail-closed** (refuses to run if approval gating is disabled);
  the bundle is **enshrined-immutable** (`S3BundleStore` writes throw after freeze);
  PostHog-wide **team-scope totality** already exists (the IDOR coverage check over
  `baseline_unmigrated.txt` enumerates team-scoped models and fails on any not on a
  fail-closed manager). We are not importing a foreign idea; we are *generalizing
  one the codebase already practices in spots.*
- **The docs are decohering** — this review's companion
  [`agent-platform-docs-inaccuracies.md`](../../../../agent-platform-docs-inaccuracies.md)
  found 5 doc-vs-code divergences in one afternoon (two-DB split, runtime-table
  ownership, a moved file path, bundle-read source, an omitted memory subsystem).
  In doctrine terms the hand-maintained map is the *convention tier* and it is
  rotting; that log *is* the per-edit ordering tax being paid by hand.

## 3. The agent platform as a trust-graded manifold

Coherence models the architecture as **charts** (local trust domains) stitched by
**transition maps** (chokepoints that re-establish the destination's invariant).
Naming them is the prerequisite for asking "is every crossing enshrined or
totality-checked?" Draft charts:

| chart | trust domain |
| --- | --- |
| `control-authoring` | Django REST + janitor — authors specs/bundles |
| `runtime-node` | ingress + runner — claims and executes sessions |
| `agent-model` | the model loop's tool surface — author/asker input, never trusted with the kernel |
| `sandbox` | author-supplied custom-tool code, isolated |
| `external-egress` | outbound HTTP, external MCP servers — leaves the trust boundary |
| `storage` | `agent_platform` postgres · bundle store · memory store |

Draft crossings (the chokepoints we'd claim and grade):

| from → to | chokepoint | invariant it re-establishes | today |
| --- | --- | --- | --- |
| `agent-model` → `owner` authority | the tool-approval gate | a gated tool can't dispatch without consent | tier-3 (per-lane, client unclassified) |
| `agent-model` → `external-egress` | smokescreen proxy-bound `http` | author URLs can't reach internal hosts (SSRF) | partial (proxy exists; no totality) |
| `agent-model` → external MCP | `PgMcpConnectionStore` credential resolve | a shared credential is used only by an authorized consumer | tier-3 (team-scoped, not owner-bound) |
| `control-authoring` → `runtime-node` | `AgentSpecSchema` (freeze ≡ start) | what the janitor freezes, the runner accepts | tier-3 (mirrored by convention) |
| `storage` (encrypted) → `runtime-node` | `EncryptedFields` ↔ Django `EncryptedJSONField` | the runner decrypts exactly what Django encrypted | tier-3 (mirror "by intent", untested) |
| `runtime-node` → `storage` | bundle freeze | a live revision's bundle is immutable | **enshrined** ✓ |

Target state (mnemion's headline): **zero tier-3 security crossings.**

## 4. The first step (concrete, one boundary, done fully)

Do **not** boil the ocean. The doctrine's own adoption arc started by taking the
single highest-consequence boundary and giving it the *whole* treatment, then
ratcheting. We propose the same:

**First boundary: the tool-authorization gate** (`agent-model → owner authority`).
It is the densest fix-cluster in the history and has a *present* hole (client
tools). Treatment:

1. **One declarative home, as data.** A single `TOOL_AUTHORIZATION` table keyed by
   tool identity that yields, for every tool regardless of lane, its
   `{ approval: allow | approve | deny }`. Native/custom/MCP/client all derive from
   it. (MCP already has `default_tool_approval` + per-tool `level`; this lifts the
   same shape to cover *all four lanes* in one place.)
2. **Derive at one chokepoint.** Collapse the per-lane gate resolution in
   `build-agent-tools` / `driver` dispatch into a single `resolveGate(toolRef)`
   that every `tool_call` physically crosses before execute — the layer the
   invariant is *about* (the dispatch), not each lane.
3. **Fail closed.** An unclassified tool resolves to `approve` (or `deny`), never
   `allow`. A new tool kind or a new registered tool that nobody classified is
   *safe by default*, and forgetting to classify it is loud, not silent.
4. **Totality oracle (the deliverable that proves the method):**
   `verifyToolAuthorizationTotality` — enumerate every shipped tool across all four
   lanes and assert each resolves a gate; fail the suite on any unclassified member.
   This is the artifact to ship first; it is small and it converts "the next
   reviewer finds the unguarded tool" into "the build asserts there is none."
5. **Enshrine the lane set.** Make `ToolKind` a discriminated union dispatched with
   an exhaustive `assertNever`, so adding a fifth lane *cannot compile* until
   dispatch (and therefore the gate) handles it.

Shipping #4 alone — a totality oracle over the existing tool surface — is the
minimal, reviewable first commit. Everything else is the ratchet.

## 5. Invariants to enshrine (answer: structural, unrepresentable)

Push these to **tier-1** — the unsafe state should not typecheck or persist:

- **E1 — Tool lanes are exhaustive.** `ToolKind` as a closed union + `assertNever`
  dispatch. An unhandled lane is a compile error. *(unblocks the §4 gate)*
- **E2 — Cross-tenant shared-connection reference is unrepresentable.** Bind a
  `connection` ref to its owner/app at spec-write time; hand the runner only a
  resolver scoped to `(owner, app)`, so referencing a teammate's installation
  *can't resolve*. Closes PR #66007 gap #6 at the type layer, not with a runtime
  `if`. *(this is the consent-gate-bug-made-unexpressible move)*
- **E3 — One encryption key source.** A single `EncryptedField` key set shared by
  Django and the runner (CLAUDE.md rule #4 states this as a convention — enshrine
  it): one constructor, a boot assertion the key is present, no second mechanism.
- **E4 — Bundle immutability** — *already enshrined*; record it as the reference
  example so the pattern is legible.
- **E5 — Approval-disabled is unrunnable** — *already enshrined* in `runSession`;
  likewise record it.

## 6. Totality oracles we need (answer: enumerable domains, fail loud)

Each enumerates a domain and fails the build on an unclassified member — **tier-2**:

- **O1 — Tool-authorization totality** *(the first step, §4.4).* Every tool in
  every lane resolves a gate; unclassified ⇒ fail.
- **O2 — Spec-schema parity.** The janitor's served `/spec-schema`, the runner's
  `AgentSpecSchema`, and the Django serializer derive from **one** home (or an
  oracle asserts they are byte-identical per version). Makes the docs' stated
  *"validate twice, same schema"* checked instead of hoped. *(directly attacks the
  drift our INACC log keeps finding)*
- **O3 — Session-state reaper totality.** Enumerate every non-terminal session
  state (`available`/`running`/`waiting`/…) and assert each has a reaper (worker
  release or janitor sweep). A new state with no sweeper ⇒ fail — no session can be
  invented that gets stuck with nothing to unstick it.
- **O4 — Native-tool registry totality.** Every `kind:'native'` id used in any
  shipped/fixture spec resolves to a registry impl (today a stale id is *silently
  skipped*); and every registry tool declares an approval class (feeds O1).
- **O5 — MCP credential-path totality.** Every `mcps[].kind` pins exactly its
  credential fields (PR #66007's refine — make it an asserted totality), and every
  credential resolves through exactly one of {connection-store, identity, secrets}
  — *no fourth path* (the thing `ec9e281` had to delete by hand).
- **O6 — Encryption interop.** A fixture encrypted by Django's `EncryptedJSONField`
  round-trips through the TS `EncryptedFields` decrypt (PR #66007 gap #2: today the
  mirror is asserted "by intent", untested) + the E3 boot assertion.
- **O7 — Egress SSRF totality.** Every author-controlled outbound fetch
  (web-fetch, http-request, MCP transport) routes through the proxy-bound `http`
  client; a raw `fetch`/`undici` in the tool surface ⇒ fail (mnemion's
  `injection-lint` analog).
- **O8 — Runtime-table team-scope.** Extend PostHog's existing model-scope oracle to
  confirm the `agent_*` runtime tables are team-scoped via fail-closed managers, and
  that node-side reads honor it (couples with E2).

## 7. The ratchet — flipping the cost gradient

A totality oracle that exists but isn't *cheaper than the workaround* will be
routed around. To make the convergent move the cheap one:

- **Run the oracles in CI** as a ratchet (mnemion: `coherence verify`, the
  boundary-oracle *mutation* harness `226e478`/`b552184` that injects a defect and
  proves the suite expels it). Start with O1 wired into the existing agent-tests CI.
- **Generate the map from the territory.** The doctrine's *"CLAUDE.md should be
  generated by Coherence, not a source of constant rot"* is the fix for our INACC
  log: derive (or drift-check) `products/agent_platform/CLAUDE.md` +
  `docs/architecture.md` against the code so a divergence fails the build instead of
  accumulating into a 5-entry errata file.
- **Scaffold, don't document.** Once O1 exists, a `scaffold boundary` that emits
  *(declaration row + red boundary claim + chokepoint/oracle TODOs)* makes the next
  boundary cheaper to add coherently than to patch — the gradient flip made real.

## 8. Recommended first commit

1. `verifyToolAuthorizationTotality` (O1) + the single `TOOL_AUTHORIZATION` home it
   reads, fail-closed, wired into agent-tests CI. *(small, reviewable, proves the method)*
2. Then E1 (exhaustive `ToolKind`) to make the gate un-routable-around.
3. Then O2 (spec-schema parity) — highest doc-drift payoff.

Everything past that is the ladder in §§5–6, sequenced by consequence.

## Appendix — provenance

- Doctrine source: mnemion `.claude/skills/mnemion-doctrine/references/doctrine.md`;
  `docs/coherence/atlas.md`; `coherence.config.json`; the convergence arc
  `11b34c7` (fail-closed reversal) · `938cc3e` (born-hashed totality) · `dab836c`
  (consent-gate made unexpressible) · `0b5d9e3`/`f5d8668` (convention→contract) ·
  `c09c7f5`/`4432d3b` (manifold/atlas, last tier-3 closed) · `226e478`/`b552184`
  (mutation ratchet).
- Agent-platform fix-cluster: `bd1f7fa`, `78f7a0ad`, `ec9e281`; PR #66007 "known gaps".
- Existing coherent boundaries: `S3BundleStore` freeze; `runSession` fail-closed
  approvals; PostHog `baseline_unmigrated.txt` model-scope oracle.
</content>
</invoke>
