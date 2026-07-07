# Repo ownership model: distributed `OWNERS.yaml`

Status: proposal (draft)
Branch: `feat/repo-ownership`

Design a single ownership source of truth that multiple consumers (review automation, CI validation, lookup CLIs, service catalogs, future tools) can read, instead of each tool re-parsing `CODEOWNERS-soft` and `product.yaml` on its own.

## 1. Survey of prior art

| System | Placement | Match resolution | Roles | Inheritance control | Metadata |
|---|---|---|---|---|---|
| GitHub CODEOWNERS | one central file | last-match-wins (whole file) | none | none | none |
| GitLab CODEOWNERS | one central file | last-match-wins per section | sections + `@@role` refs | section-scoped | none |
| Gerrit/Chromium OWNERS | per directory | ancestor union | none (Gerrit labels) | `set noparent`, `per-file` | sibling DIR_METADATA (component, team contact) |
| Kubernetes/Prow OWNERS | per directory, YAML | ancestor union | `approvers` vs `reviewers` | `options.no_parent_owners` | `labels`, `emeritus_approvers`, root `OWNERS_ALIASES` |
| Backstage catalog-info.yaml | per component | explicit reference, no globs | typed `spec.owner` (Group) | n/a | open-ended annotations |

Lessons that shaped this proposal:

- Central single-file systems rot via pattern-order bugs: last-match-wins makes line order load-bearing, and a broad glob added late silently swallows earlier specific rules. Our own `CODEOWNERS-soft` already relies on deliberate ordering (the managed-reverse-proxy block must stay last).
- Per-directory files match the mental model ("who owns *this* directory") and scale with a monorepo, but need a coverage audit tool since nothing forces a new directory to get an owner.
- The approver/reviewer split (Kubernetes) is the single most useful role distinction: "can gate a merge" vs "should see this PR" are different sets. We already have exactly this split — hard `CODEOWNERS` vs soft — just encoded as two separate files with different formats and different consumers.
- Chromium separates approval (OWNERS) from routing metadata (DIR_METADATA: team contact, bug component). Keeping "who approves" and "who to page/ping" in one schema but different fields avoids a second file.
- Kubernetes avoids GitHub Teams for grouping (no audit trail for membership) via a PR-reviewable `OWNERS_ALIASES` file. We *do* want GitHub team slugs (the auto-assigner needs them), but an alias layer still helps for individuals and virtual groups.
- The compile-to-CODEOWNERS pattern (structured YAML as source, flat CODEOWNERS as build artifact) is common and keeps native platform integration for free.

## 2. What the repo has today

Two data sources, one shared matcher, four consumers — all hand-maintained, three of them with their own parsers.

**Sources**

- `.github/CODEOWNERS` (58 lines): blocking. Deliberately tiny, infra/security-critical trees only ("extraordinary justification" header). Uses owner-less lines as *resets* to clear a blocking owner for a subtree (e.g. `posthog/hogql/database/schema/**`).
- `.github/CODEOWNERS-soft` (383 lines): non-blocking review tagging. Carries all product mapping for shared code outside `products/` (~25 teams). Header already says: product-level ownership belongs in `product.yaml`; this file is for sub-folder overrides, secondary reviewers, and paths outside `products/`.
- `products/*/product.yaml` (68 files): exactly two fields, `name` and `owners` (list of team slugs, occasionally `@individual`). Owns all of `products/<name>/**` and beats any CODEOWNERS entry in the resolution used by the ownership skill.

**Consumers and their parsers**

| Consumer | Reads | Parser |
|---|---|---|
| `.github/scripts/assign-reviewers.js` (CI auto-assign) | soft + product.yaml | vendored matcher + own YAML mini-parser |
| `hogli product:lint:owners` | product.yaml | own loader (`product_yaml.py`), validates slugs against live GitHub teams |
| `.agents/skills/establishing-code-ownership/ownership.js` | hard + soft + product.yaml | vendored matcher + own YAML mini-parser |
| `tools/pr-approval-agent/gates.py` | soft only | fully independent reimplementation |

The vendored matcher is `.github/scripts/codeowners.js` (a port of `hmarr/codeowners`, faithful to GitHub semantics).

**Gaps**

- Four parsers of the same two files; only two share the matcher. Drift is a when, not an if.
- Only `product.yaml` is CI-validated. Nothing checks that `CODEOWNERS-soft` globs still match existing files or that its team slugs exist (the assigner discovers dead teams at runtime via 422s).
- No schema for `product.yaml`; no oncall/Slack/escalation routing anywhere in the repo (handbook only).
- Consumers disagree about scope: the assigner and pr-approval-agent ignore the hard file; only the skill layers all three sources.
- No structured notion of generated/vendored/deprecated code — the assigner hardcodes an ignore list (`frontend/src/generated/**`, `*.ambr`, lockfiles, …).

## 3. Proposed canonical format: `OWNERS.yaml`

One schema, distributed per directory, plus a root alias file. `product.yaml` `owners:` folds into `products/<name>/OWNERS.yaml` (see migration).

```yaml
# OWNERS.yaml — full form; every field except `team` is optional
version: 1

# The one required field: the responsible team. GitHub slug minus @PostHog/,
# or an alias from OWNERS_ALIASES.yaml.
team: team-error-tracking

# Non-blocking PR review tagging (defaults to [team] when omitted).
reviewers: [team-error-tracking]

# Blocking merge gate — compiles into .github/CODEOWNERS. Deliberately rare;
# adding this field anywhere carries the same "extraordinary justification"
# bar the hard CODEOWNERS header sets today.
approvers: [team-security]

# Additional blocking gate for security-sensitive paths; kept separate from
# approvers so audits can enumerate security-gated surface directly.
security_reviewers: []

# Routing metadata (Chromium DIR_METADATA role) — never affects review gates.
contact:
  slack: '#team-error-tracking'
  oncall: pagerduty:error-tracking   # opaque, scheme-prefixed reference

# Lifecycle of the code under this directory.
# active (default) | deprecated | generated | vendored | shared
status: active

# When true (default), fields not set here fall through to the nearest
# ancestor OWNERS.yaml. false = Gerrit's `set noparent`.
inherit: true

# Per-path overrides inside this directory, evaluated last-match-wins
# *within this file only*. Any top-level field can be overridden per rule.
rules:
  - match: 'generated/**'
    status: generated
  - match: 'vendor/**'
    status: vendored
    team: null            # explicit reset: unowned-by-design, lint-exempt
  - match: 'migrations/**'
    reviewers: [team-error-tracking, team-data-modeling]
```

The 90% case is two lines:

```yaml
# products/error_tracking/OWNERS.yaml
version: 1
team: team-error-tracking
```

Root alias file, PR-reviewable like Kubernetes' `OWNERS_ALIASES`:

```yaml
# OWNERS_ALIASES.yaml
version: 1
aliases:
  user-interviews-maintainers: ['@pauldambra', '@fivestarspicy', '@ksvat']
  hogql-core: [team-analytics-platform]
```

Aliases are the only place individuals appear; `team:`/`reviewers:` elsewhere take team slugs or alias names. This solves the current `user_interviews` hack (individuals wired through both `product.yaml` comments and `CODEOWNERS-soft`), and makes team renames a two-file diff.

### Design choices, argued

- **Distributed, not central.** The repo already voted: `product.yaml` is per-directory and the soft file's own header pushes ownership toward it. Central files are what we're escaping (ordering bugs, merge conflicts on one hot file). The audit story ("show me everything") is a tool's job (`hogli owners:map`), not a file layout's.
- **Nearest-file-wins with per-field fallthrough, not ancestor union.** Kubernetes unions approvers up the tree because its bar is "someone must approve"; our soft model is "tag the right team, don't spam five". Union inheritance would tag `posthog/` owners on every deep PR. Override semantics also match what the ownership skill already implements (product.yaml beats CODEOWNERS). Fallthrough is per field: a child file that only sets `reviewers` still inherits `team` and `contact` from its ancestor.
- **`rules:` are file-local.** Cross-file glob interactions are the CODEOWNERS footgun; here a glob can only override its own directory's defaults, so reading one file plus its ancestors fully explains any path.
- **`team: null` is explicit, not absent.** Unowned must be a decision (vendored code, scratch dirs), never a default. The coverage check treats missing resolution as an error and `team: null` as an exemption with a paper trail.
- **`status:` replaces hardcoded ignore lists.** The assigner's generated-file ignore list, review-noise suppression, and future tooling (e.g. excluding vendored code from lint) all key off one field instead of N copies.

## 4. Resolution model

For a path `P`:

1. Walk from the repo root toward `P`, collecting every `OWNERS.yaml` on the way. If a file sets `inherit: false`, drop everything collected above it.
2. Effective config = shallow merge, nearest file winning per field (lists replace, never merge — predictability over cleverness).
3. Within the nearest file that has `rules:`, apply the last rule whose `match` glob (GitHub CODEOWNERS semantics, via the vendored matcher) matches `P` relative to that file's directory. Rule fields override the merged config.
4. Blocking gate for `P` = resolved `approvers` + `security_reviewers` (empty for almost the whole tree). Review tagging = resolved `reviewers`. Responsible team = resolved `team`.
5. No `OWNERS.yaml` on the walk and no rule match → **unowned**, which fails the coverage check unless the path is under a `team: null` rule.

During migration, legacy sources slot into this walk at fixed precedence: `OWNERS.yaml` > `product.yaml` `owners:` > hard `CODEOWNERS` > `CODEOWNERS-soft` — i.e. today's skill algorithm with `OWNERS.yaml` layered on top, so the two systems coexist without ambiguity.

## 5. Tool independence: one resolver, many consumers

The stability guarantee is architectural: **consumers never parse `OWNERS.yaml` themselves.** One resolver library owns the semantics; everything else calls it or reads its compiled output.

- **Resolver**: single implementation (TypeScript, colocated with the vendored matcher in `.github/scripts/`, since three of four consumers are JS and CI runs it). Exposes `resolve(path)`, `map()`, `unowned()`.
- **Compiled snapshot**: `hogli owners:compile` emits
  - `.github/CODEOWNERS` — generated from `approvers`/`security_reviewers` fields, `DO NOT EDIT` header, checked in. GitHub keeps enforcing natively; the file stays tiny by construction. (A `.gitlab/CODEOWNERS` emitter is the same fold over the same graph, if ever needed.)
  - `.github/CODEOWNERS-soft` — generated from `team`/`reviewers` during migration, deleted once all consumers read the resolver.
  - `owners.lock.json` — flat `{path-prefix → resolved record}` snapshot for non-JS consumers (`gates.py` reads this instead of reimplementing parsing; Backstage `catalog-info.yaml` or any future catalog is another trivial emitter over it).
- **Validator**: `hogli owners:lint` — schema check, team slugs against live GitHub org (reusing `product/gh.py`), alias resolution, dead `rules:` globs (match zero files), full-tree coverage (every `git ls-files` path resolves or is `team: null`), and compiled-artifact freshness (CI fails if `OWNERS.yaml` changed but `CODEOWNERS` wasn't regenerated — same pattern as generated API types).
- **Lookup**: `hogli owners:who <path>` / `owners:team <slug>` / `owners:unowned` — replaces `ownership.js` internals; the skill becomes a thin wrapper.

If the first consumer (say the auto-assigner) is ever replaced, the graph, resolver, lint, and lock file are untouched — only one emitter or caller changes. That is the "source of truth, not tool config" property.

## 6. Migration plan

1. **Schema + resolver + lint, no behavior change.** Land `OWNERS.yaml` schema, resolver, `owners:lint` (warn-only coverage). Legacy files remain authoritative; resolver layers them per §4.
2. **Products.** Generate `products/<name>/OWNERS.yaml` from each `product.yaml` `owners:`; `product.yaml` drops `owners` (or keeps it temporarily with lint enforcing equality). Scaffold (`product:bootstrap`) emits `OWNERS.yaml` with `team: team-CHANGEME` and lint rejects the placeholder, as today.
3. **Shared trees.** Convert `CODEOWNERS-soft` blocks into distributed `OWNERS.yaml` under `posthog/`, `frontend/src/scenes/`, `rust/`, `nodejs/`, `services/`, `ee/`. Verify with a differ: compiled soft output must match the hand-written file's resolution for every tracked path before the hand-written file is deleted. Flip `assign-reviewers.js` and `gates.py` to the resolver/lock file — this deletes three of the four hand-rolled parsers.
4. **Hard gate last.** `approvers:`/`security_reviewers:` fields for the few blocking trees; `.github/CODEOWNERS` becomes generated. The generator, resolver, and workflow stay owned by `team-security` (`approvers: [team-security]` on `.github/scripts/`), so gate changes still require their approval — same self-governance as today, now expressed in the model itself.
5. **Coverage ratchet.** Flip `owners:lint` coverage from warn to fail once unowned paths hit zero (or are explicitly `team: null`).

## 7. Open questions for maintainers

1. **Union vs override for blocking approvers.** §4 uses nearest-wins for everything. Should `approvers` instead union up the tree (a subtree can add a gate but never remove one) with resets requiring `inherit: false`? Safer for security gates; the current hard file's owner-less "reset" lines suggest removal is a real need. Recommendation: union for `approvers`/`security_reviewers` only, with resets expressed as an explicit `approvers: []` + a required comment — but this deserves a security-team opinion.
2. **Does `contact:` (slack/oncall) belong in-repo at all,** or does that stay in the handbook/PagerDuty and the schema stays approval-plus-routing-free? In-repo means one more thing to go stale; out-of-repo means the graph can't drive paging integrations.
3. **`product.yaml` fate**: fold `owners` out (leaving `name` only) or deprecate `product.yaml` entirely into `OWNERS.yaml` + a `product: <display name>` field?
4. **Where the resolver lives**: `.github/scripts/` (JS, near consumers, security-owned) vs a `tools/` package published to the workspace. JS in `.github/scripts/` is the recommendation; confirm hogli calling into node is acceptable (it already shells out elsewhere).
5. **Individuals as owners**: keep supporting them via aliases only (recommended), or ban them and force team creation (`user_interviews` is the only current case)?
6. **How aggressively to gate coverage**: fail CI on any unowned *new* directory immediately (cheap, ratchet-style) vs waiting for full-tree coverage first.
