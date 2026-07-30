# Coherence — the doctrine and the harness

The transferable half of this stack: the doctrine that says _why_ we build boundaries
this way (Danilo's Mnemion doctrine), and the harness that checks them
([daniloc/coherence](https://github.com/daniloc/coherence)). For the concrete inventory of
what we actually built here, see [coherence-overview.md](coherence-overview.md). Read this
before authoring or maintaining a boundary.

## The doctrine

> A recurring bug is a structural question answered at call sites instead of at a boundary.
> Don't patch faster: invert the architecture so the bug becomes **unrepresentable**.

The fix-one-open-another loop _is_ the diagnosis. When two findings cluster on one seam,
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

**The linchpin: prove totality.** A chokepoint is not enough; you must _know_ it's the only
path. A totality oracle converts the unanswerable block-list question ("did we find every
sink?") into a checkable one ("does the one declaration cover the enumerable domain, and
fail loud if not?"). A boundary without an oracle is a half-boundary; don't ship it.

**Capability over convention.** An oracle proves the _anatomy_ exists (the chokepoint
symbol, the green test). It cannot prove the chokepoint is un-routable-_around_: that comes
from the type system. A named capability constructor with no trust parameter to dial at a
call site makes the wrong call _unexpressible_, not merely guarded. Conventions are failures
lurking in the code; we want contracts.

**The graded ladder (match rigor to consequence).** _enshrined_ (the unsafe state is
unrepresentable in types) > _totality-checked_ (an oracle proves the N sites agree) >
_convention_ (held by memory). Push security boundaries up; the target is zero security
rules at the convention tier. Don't over-enshrine: making every crossing a ceremony is its
own inner-platform pathology.

**The manifold this describes.** Charts (trust domains: owner-trusted, served-untrusted,
agent-mcp, public-egress, ...) stitched by transition maps (the chokepoints). Trust is
directional: most crossings preserve or lower it, only an _enshrined_ crossing may raise it.
A convention crossing is where the manifold can tear. The **atlas** is that map made
legible: it derives each crossing's tier from the live boundary claims and flags any
tier-3 security crossing. (We haven't built the atlas layer here yet; it's the next increment.)

**The metric: blast radius.** How many files an agent must read and keep in sync to add one
invariant. Drive it toward one, and make the convergent move the _cheapest_ one, or the
divergent move is the one that gets made.

> In one breath: one declarative home (data, not convention) → derive every gate → enforce
> at the chokepoint all paths cross → fail closed → assert totality so the absence of holes
> is _checked_, not hoped → make the boundary un-routable in types → keep intent, structure,
> and evolution converged.

## The harness

`coherence` is a zero-dependency Node CLI that derives a graph from a `*.spec.md` tree plus
the code, then verifies the claims haven't rotted. The core is language- and
platform-agnostic; TypeScript and Python adapters cover this repo. Its one load-bearing
feature: a `boundary` claim welds a declared **invariant** → a **chokepoint symbol** → a
**totality oracle**, and fails the build if the oracle is renamed, deleted, or missing.
Reach for it when a correctness commitment must _stay_ enforced under future edits, not for
one-off bugs.

### Claim grammar (the part to get right)

Each claim in a spec's `## works when` list is verified at one tier:

- **structural** (instant): `typechecks` · `X exists` · `X imports Y`.
- **executable**: `passes test "<name>"` shells the test runner with `<name>`. This is the
  _single front door_: an invariant enforced by a test is named in the spec, so `verify`
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
3. **The meta-oracle proves anatomy, not semantics.** It proves the oracle _iterates a live
   domain_; it cannot prove the assertion exercises the real enforcement rather than a
   _proxy_. A unit test with a fake DB asserting the owner arg was _passed_ stays green while
   the SQL `WHERE owner` predicate is deleted and the IDOR reopens.
4. **`decompose` / `drift` are degenerate with a single node:** they need a real multi-node
   spec tree to say anything.

**The discipline: validate by perturbation, not by a green run.** For every boundary: revert
the fix (or inject the exact violation the invariant forbids) → confirm the oracle goes
**red** → restore. If it stays green, the oracle tests a proxy; rewrite it against the real
mechanism. The layered defense is `oracle → meta-oracle → perturbation`, each catching what
the layer below can be fooled about; the injection is ground truth. For an impact read,
inject a _fair_ set: in-domain violations, out-of-domain logic bugs (blind spots), and
benign edits (false alarms), and score which go red.

## Setup and the local gate

```sh
git clone --branch v0.9.0 https://github.com/daniloc/coherence.git /tmp/coherence
cd /tmp/coherence && npm ci --ignore-scripts && npm run build   # → dist/cli.js (Node ≥22, zero runtime deps)
```

The gate pins `daniloc/coherence` at commit `bb40f4a` (v0.9.0) — see
`bin/coherence-install`. v0.9.0 carries everything the gate leans on: `it.each` domain
recognition, domain-floor detection, the NOT-FOUND hard-fail on `via test`, the `parity`
claim type, Python support, and markdown-escape-robust claim parsing. For eventual CI
adoption it installs as a git dependency (`github:daniloc/coherence`) rather than a clone.

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

Set `testMatch`: without it a runner like `vitest -t` exits 0 even when the name matched
nothing, and a deleted oracle stays green.

The harness is **not wired into CI** (a personal-repo tool, deliberately local-only for a
one-week evaluation). The gate is a **local pre-commit hook**, scoped to agent_platform, and
it **self-installs on first use**: your first commit touching `products/agent_platform/**`
does a one-time clone + build of the pinned CLI into a gitignored cache (`.coherence-tool/`),
then runs two cheap gates in each coherence root you touched — `coherence verify --fast`
(structural claims + boundary anchoring + the meta-oracle; no DB, no test runner) and
`coherence log --strict` (the loss-ratchet: reds if the commit drops an invariant/boundary/
parity) — and blocks the commit on a red from either. Run
`products/agent_platform/bin/coherence-install` upfront if you'd rather not wait on that first
commit. It's wired through lint-staged, so it fires only for agent_platform changes; bypass a
single commit with `git commit --no-verify`. If the install can't run (offline), it skips that
commit and retries next time rather than blocking.

What the fast pre-commit catches locally: an unanchored invariant, a renamed or missing
chokepoint symbol, a vacuous or weak oracle (the meta-oracle), a missing floor (all via
`verify`), plus a _dropped_ invariant/boundary/parity (via `log --strict` — so the cheapest
way to green a failing `verify`, deleting the claim, is caught too). What it does **not** run
is the oracle tests themselves (real DB / real dispatch) — those are ordinary vitest/pytest
tests that run in CI regardless, so a semantic regression is still caught there. The
pre-commit is advisory-by-consent (bypassable, and only for whoever has it installed); the
same `verify` + `log --strict` in CI would be unbypassable enforcement, but that's a
deliberate not-yet for this one-week evaluation.
The declared invariants live in the `*.spec.md` next to the code — read the ones in any
directory you edit; they are the checklist of what your change must not break.

## Backing this out

This is a one-week evaluation, so the exit is designed to be clean. The one thing to
understand first: the adoption PR squash-merges into a single commit on master that carries
**two** things — the harness (this tooling + the `*.spec.md` claims + per-root config) _and_
real chokepoint hardening (IDOR / owner-scoping / bug-class fixes in `*.ts`). Those are woven
into the same squash.

**Do not `git revert` that commit.** It would undo the hardening too and reopen the exact bug
classes the branch closed. Removing coherence means removing the _harness_ while keeping the
_hardening_. Three tiers, easiest first:

1. **Disable, don't remove (instant, zero-risk).** The gate is a _local_ pre-commit hook, not
   CI. Delete the one lint-staged line in `package.json`
   (`"products/agent_platform/**/*.{ts,py}": ".../coherence-precommit"`) and the gate goes
   dormant for everyone immediately; the specs and configs become inert. This is the real
   "call off the evaluation" move — no history rewrite.
2. **Full teardown (later, at leisure).** Run
   [`bin/coherence-uninstall`](../bin/coherence-uninstall). It removes exactly the harness —
   every `coherence.config.json`, every `*.spec.md`, the CLI scripts, the docs, the gitignored
   caches — and prints the one manual step (the `package.json` line, which it won't edit
   blindly). It touches no `*.ts` / `*.test.ts`: a test that enumerates its domain is a better
   test whether or not coherence reads it, so those stay.
3. **Never the blunt revert** — see above.

The oracle test files, the `mcp_store` facade, and the `pyproject.toml` / `tach.toml` edits are
hardening, not harness; they survive all three tiers.

## Command reference

- `verify [--fast|--staged|--since <ref>]`: run claims + boundary anchoring + coverage.
  `--staged`/`--since` scope to changed components; `--fast` skips executable/live claims.
- `log [--strict]`: the temporal ledger of which invariants/boundaries a diff added, removed,
  or rewired. `--strict` exits nonzero on a _loss_, so a PR can't silently drop a guard.
- `decompose`: LOCALITY report, how much co-change stays inside one component (three-graph
  agreement). Advisory.
- `drift`: decompose's derivative, is the agent converging (one concern, one home) or
  decohering (concerns smearing)? Names the hot seam. Advisory.
- `scaffold <boundary|component|invariant> <name>`: emits the complete shape so you can't
  ship a half-boundary (the gradient flip).
- `why-lint [--check]`: flags `## why` prose that re-states an anchored mechanism, and
  invariants/paragraphs left un-anchored.
- `onboard` · `graph` · `overview` · `docs [--check]`: bootstrap and doc generation.

## Honest limits

- Oracles can be proxies; only perturbation catches that.
- `via guard` source-scans are brittle to renames; watch their friction.
- It's a personal-repo git dependency: a supply-chain consideration before CI adoption.
- Where it's the _wrong_ tool: effects (the dispatch may be tabular, the handler stays
  imperative), one-offs (a table of one is worse than an `if`), and history (migrations and
  audit logs are point-in-time by design; you can't derive them).
