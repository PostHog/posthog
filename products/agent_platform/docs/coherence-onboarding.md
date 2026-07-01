# Coherence — the doctrine and the harness

The transferable half of this stack: the doctrine that says *why* we build boundaries
this way (Danilo's Mnemion doctrine), and the harness that checks them
([daniloc/coherence](https://github.com/daniloc/coherence)). For the concrete inventory of
what we actually built here, see [coherence-overview.md](coherence-overview.md). Read this
before authoring or maintaining a boundary.

## The doctrine

> A recurring bug is a structural question answered at call sites instead of at a boundary.
> Don't patch faster: invert the architecture so the bug becomes **unrepresentable**.

The fix-one-open-another loop *is* the diagnosis. When two findings cluster on one seam,
stop patching sinks and enforce the invariant from a single home.

**The conversion, O(N) → O(1).** Turn a **block-list** (N guards you must remember at N
sinks; fails open the moment one is forgotten) into a **chokepoint** (one reference monitor
every path physically crosses). A chokepoint earns trust from four properties that must
travel together:

1. **One declarative home, and it's data.** A table keyed by the thing it governs: not a
   predicate copied across sites, not a naming convention standing in for an unmodeled fact,
   not prose in a doc.
2. **Derive, never duplicate.** Every gate computes from the table.
3. **Enforce where the invariant lives:** the chokepoint all paths cross on the protected
   thing, not the convenient layer.
4. **Fail closed.** Absence resolves to the safe state; forgetting to update the table is safe.

**The linchpin: prove totality.** A chokepoint is not enough; you must *know* it's the only
path. A totality oracle converts the unanswerable block-list question ("did we find every
sink?") into a checkable one ("does the one declaration cover the enumerable domain, and
fail loud if not?"). A boundary without an oracle is a half-boundary; don't ship it.

**Capability over convention.** An oracle proves the *anatomy* exists (the chokepoint
symbol, the green test). It cannot prove the chokepoint is un-routable-*around*: that comes
from the type system. A named capability constructor with no trust parameter to dial at a
call site makes the wrong call *unexpressible*, not merely guarded. Conventions are failures
lurking in the code; we want contracts.

**The graded ladder (match rigor to consequence).** *enshrined* (the unsafe state is
unrepresentable in types) > *totality-checked* (an oracle proves the N sites agree) >
*convention* (held by memory). Push security boundaries up; the target is zero security
rules at the convention tier. Don't over-enshrine: making every crossing a ceremony is its
own inner-platform pathology.

**The manifold this describes.** Charts (trust domains: owner-trusted, served-untrusted,
agent-mcp, public-egress, ...) stitched by transition maps (the chokepoints). Trust is
directional: most crossings preserve or lower it, only an *enshrined* crossing may raise it.
A convention crossing is where the manifold can tear. The **atlas** is that map made
legible: it derives each crossing's tier from the live boundary claims and flags any
tier-3 security crossing. (We haven't built the atlas layer here yet; it's the next increment.)

**The metric: blast radius.** How many files an agent must read and keep in sync to add one
invariant. Drive it toward one, and make the convergent move the *cheapest* one, or the
divergent move is the one that gets made.

> In one breath: one declarative home (data, not convention) → derive every gate → enforce
> at the chokepoint all paths cross → fail closed → assert totality so the absence of holes
> is *checked*, not hoped → make the boundary un-routable in types → keep intent, structure,
> and evolution converged.

## The harness

`coherence` is a zero-dependency Node CLI that derives a graph from a `*.spec.md` tree plus
the code, then verifies the claims haven't rotted. The core is language- and
platform-agnostic; TypeScript and Python adapters cover this repo. Its one load-bearing
feature: a `boundary` claim welds a declared **invariant** → a **chokepoint symbol** → a
**totality oracle**, and fails the build if the oracle is renamed, deleted, or missing.
Reach for it when a correctness commitment must *stay* enforced under future edits, not for
one-off bugs.

Practical guide to the `coherence-harness` ([daniloc/coherence](https://github.com/daniloc/coherence))
in this repo. The upstream README covers the concepts; this front-loads the
**traps that will bite you** and the **validation discipline that makes it worth
anything** — both learned by actually running it, not reading it.

**Status here:** evaluated as a spike (see
[proposals/coherence-adoption-step-1.md](proposals/coherence-adoption-step-1.md)).
The harness is not yet wired into CI or committed as a dependency; it was built
standalone and pointed at `products/agent_platform/services/agent-shared`.

## What it is / when to reach for it

A zero-dependency Node CLI that derives a graph from a `*.spec.md` tree + the
code, then **verifies the docs/claims haven't rotted**. Its one load-bearing
feature: a `boundary` claim ties a declared **invariant** → a **chokepoint
symbol** → a **totality oracle test**, and fails the build if the oracle is
renamed, deleted, or missing. Reach for it when you have a security/correctness
commitment you need to _stay_ enforced under future edits — not for one-off bugs.

Each claim in a spec's `## works when` list is verified at one tier:

- **structural** (instant): `typechecks` · `X exists` · `X imports Y`.
- **executable**: `passes test "<name>"` shells the test runner with `<name>`. This is the
  *single front door*: an invariant enforced by a test is named in the spec, so `verify`
  runs it, and a claim pointing at a renamed or deleted test goes **red**.
- **boundary** (the ratchet): `boundary "<inv>" at <symbol> [via test|guard "<oracle>"]`.
  `via test` means a live-domain totality oracle (loops an imported SSOT / call result / the
  anchor). `via guard` means a source-property assertion with no enumerable domain.

The gate: every name in a spec's `## invariants` list **must** be anchored by a `boundary`
claim, or coverage fails. That is the doctrine made machinery: you can't ship a
half-boundary. Coverage gates node-contract completeness (claims + a `## why`), not a
docblock on every symbol.

### Authoring boundaries without fooling yourself

The ratchet is only as honest as the oracle behind it. Four edges, all found by running it:

1. **`via test "<name>"` must name a `describe`, not an `it()`.** The meta-oracle resolves
   the oracle by `describe` title; an `it()` name resolves not-found and falls through to the
   runner, so the claim goes green off the passing test and the meta-oracle never judges it.
   Name the `describe` after the invariant.
2. **Oracle names are regex.** `-t "<name>"` treats parens and brackets as groups that can
   match nothing, surfacing as `0 passed`, not a failure. Keep titles free of regex metacharacters.
3. **The meta-oracle proves anatomy, not semantics.** It proves the oracle *iterates a live
   domain*; it cannot prove the assertion exercises the real enforcement rather than a
   *proxy*. A unit test with a fake DB asserting the owner arg was *passed* stays green while
   the SQL `WHERE owner` predicate is deleted and the IDOR reopens.
4. **`decompose` / `drift` are degenerate with a single node:** they need a real multi-node
   spec tree to say anything.

**The discipline: validate by perturbation, not by a green run.** For every boundary: revert
the fix (or inject the exact violation the invariant forbids) → confirm the oracle goes
**red** → restore. If it stays green, the oracle tests a proxy; rewrite it against the real
mechanism. The layered defense is `oracle → meta-oracle → perturbation`, each catching what
the layer below can be fooled about; the injection is ground truth. For an impact read,
inject a *fair* set: in-domain violations, out-of-domain logic bugs (blind spots), and
benign edits (false alarms), and score which go red.

## Setup and the local gate

```sh
git clone --branch v0.5.3 https://github.com/daniloc/coherence.git /tmp/coherence
cd /tmp/coherence && npm install && npm run build   # → dist/cli.js (Node ≥22, zero runtime deps)
```

Pin `daniloc/coherence` at commit `f0b7319` or later: earlier mains lack `it.each` domain
recognition, domain-floor detection, the NOT-FOUND hard-fail on `via test`, Python support,
and markdown-escape-robust claim parsing. For eventual CI adoption it installs as a git
dependency (`github:daniloc/coherence`) rather than a clone.

Each node service is its own root and ships a `coherence.config.json`:

```json
{
  "outputDir": ".coherence-out",
  "entryDir": "src",
  "ignore": ["node_modules", "dist", ".coherence-out"],
  "codeExt": ["ts"],
  "typecheck": ["npx", "tsc", "--noEmit", "-p", "."],
  "test": ["npx", "vitest", "run", "-t"],
  "testMatch": "[1-9][0-9]* passed",
  "language": "typescript"
}
```

Run: `node /tmp/coherence/dist/cli.js <command>` from that root.

## Workflow

1. `onboard` — bootstrap: derives structure, drafts a spec, emits why-from-history jobs.
2. Author `<Name>.spec.md` in the folder that is the node. Grammar: `# Name`,
   one-line intent, `## invariants` (bullet list), `## works when` (claims),
   `## why`.
3. `verify` — runs claims + the `## invariants` anchoring gate + coverage.
4. **Validate by defect injection** (see below) — the step that actually matters.
5. CI: `verify --staged` (edit-loop) + `verify` + `log --strict` (blocks a PR
   that silently drops a boundary).

### The local gate (this repo, today)

`verify` is not wired into this repo's CI — the harness is a personal-repo tool,
deliberately local-only for now. The gate is therefore a workflow rule: **before
committing changes under `products/agent_platform/services/agent-*`, run
`node <coherence-cli> verify` in each service you touched** (every `agent-*`
service ships a `coherence.config.json`). The declared invariants live in the
`*.spec.md` files next to the code — read the ones in any directory you edit;
they are the checklist of what your change must not break, and each points at
the oracle that will catch you in CI (the oracles themselves are ordinary
vitest/pytest tests and run there regardless).

### Claim grammar (the part to get right)

- `typechecks` / `X exists` / `X imports Y` — structural, instant.
- `passes test "<name>"` — executable; shells `config.test` + `<name>`.
- `boundary "<inv>" at <symbol> [via test|guard "<oracle>"]` — the ratchet.
  `via test` ⟹ the oracle must be a **live-domain totality** (loops an imported
  SSOT / call result / the anchor symbol). `via guard` ⟹ a **source-property**
  check (a grep-style assertion with no enumerable domain).
- Any invariant in `## invariants` **must** be anchored by a `boundary` claim or
  coverage FAILS ("can't ship a half-boundary").

## Traps that will bite you (all hit during the eval)

1. **`via test "<name>"` must name a `describe` block, NOT an `it()`.** The
   meta-oracle (`oracle-domain.ts`) locates the oracle by `describe` title. Point
   it at an `it()` name and it resolves **not-found → silently falls through to
   the runner** — the meta-oracle goes inert and never tells you the oracle is
   weak. **Name the `describe` after the invariant.**
2. **Oracle names are regex.** `via test` runs `vitest -t "<name>"`, and `-t` is
   a regex. Parentheses/brackets in a test name become regex groups and can match
   **nothing** — which shows as `0 passed` / "matched no run", _not_ a failure.
   Keep boundary-oracle `describe` titles free of regex metacharacters.
3. **A green boundary is NOT proof the invariant holds.** The oracle can test a
   _proxy_. Real example here: the connection-owner IDOR oracle was a **fake-pool
   unit test asserting the owner arg was _passed_** — it stayed green while the
   SQL `WHERE owner` predicate was deleted and the IDOR reopened. Anchor
   boundaries to oracles that exercise the **real enforcement** (real DB, real
   dispatch), not a correlate. The fix was a temp-table test running the actual
   `SELECT` against two owners (`mcp-connection-store.sql.test.ts`).
4. **The meta-oracle checks anatomy, not semantics.** It verifies the oracle
   _iterates a live domain_; it **cannot** tell that the assertion exercises the
   real mechanism vs a proxy. Passing the meta-oracle ≠ testing the right thing.
5. **`decompose` / `drift` are degenerate with one node.** They need a real
   multi-node spec tree to say anything; a single component reads as trivially
   100% local.
6. Whole-suite `-t` is fine for DB-backed oracles: vitest skips `beforeAll` for
   non-matching files, so only the matched oracle's services spin up.

## Validate boundaries by defect injection (the discipline)

**Do not trust a green `verify`.** For every boundary, prove the oracle bites:

> Revert the fix (or inject the violation the invariant forbids) → confirm the
> oracle goes **RED** → restore. If it stays green, the oracle tests a proxy —
> rewrite it against the real enforcement.

This is the only method that tests _semantics_. The layered defense is
`oracle → meta-oracle → defect injection`, each catching what the layer below can
be fooled about; the injection is ground truth. For a real impact read, inject a
_fair_ set — in-domain violations **plus** out-of-domain logic bugs (to measure
blind spots) **plus** benign changes (to measure false alarms) — and score which
go red. Coherence catches boundary-class regressions; it catches nothing outside
its declared boundaries, and a green run can lull you on exactly those.

## The graded ladder (match rigor to consequence)

`enshrined` (unsafe state unrepresentable in types — e.g. a capability split) >
`totality-checked` (`via test`, live-domain oracle) > `guard` (`via guard`,
source-property) > `convention` (memory/doc — the state to leave). Push boundaries
_up_; don't over-enshrine (that's its own inner-platform pathology).

## Honest limits

- Oracles can be proxies; only perturbation catches that.
- `via guard` source-scans are brittle to renames; watch their friction.
- It's a personal-repo git dependency: a supply-chain consideration before CI adoption.
- Where it's the *wrong* tool: effects (the dispatch may be tabular, the handler stays
  imperative), one-offs (a table of one is worse than an `if`), and history (migrations and
  audit logs are point-in-time by design; you can't derive them).
