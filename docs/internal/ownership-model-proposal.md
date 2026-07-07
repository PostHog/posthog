# Repo ownership model: distributed `OWNERS.yaml`

Status: proposal (draft)
Branch: `feat/repo-ownership`

Design a single ownership source of truth that multiple consumers (review automation, CI validation, lookup CLIs, service catalogs, future tools) can read, instead of each tool re-parsing `CODEOWNERS-soft` and `product.yaml` on its own.

Scope decisions (locked):

- `OWNERS.yaml` becomes the canonical ownership format.
- `.github/CODEOWNERS-soft` is deleted; the PR-assignment flow reads the new resolver instead.
- `products/*/product.yaml` stays and is an **accepted alias** of `OWNERS.yaml` — its `owners:` key is a first-class ownership source, all other fields are ignored for ownership purposes.
- The hard `.github/CODEOWNERS` is left alone for now: hand-maintained, GitHub-enforced, out of the schema.
- Everything lands in **one PR**.

## 1. Survey of prior art

| System                      | Placement           | Match resolution             | Roles                      | Inheritance control        | Metadata                                              |
| --------------------------- | ------------------- | ---------------------------- | -------------------------- | -------------------------- | ----------------------------------------------------- |
| GitHub CODEOWNERS           | one central file    | last-match-wins (whole file) | none                       | none                       | none                                                  |
| GitLab CODEOWNERS           | one central file    | last-match-wins per section  | sections + `@@role` refs   | section-scoped             | none                                                  |
| Gerrit/Chromium OWNERS      | per directory       | ancestor union               | none (Gerrit labels)       | `set noparent`, `per-file` | sibling DIR_METADATA (component, team contact)        |
| Kubernetes/Prow OWNERS      | per directory, YAML | ancestor union               | `approvers` vs `reviewers` | `options.no_parent_owners` | `labels`, `emeritus_approvers`, root `OWNERS_ALIASES` |
| Backstage catalog-info.yaml | per component       | explicit reference, no globs | typed `spec.owner` (Group) | n/a                        | open-ended annotations                                |

Lessons that shaped this proposal:

- Central single-file systems rot via pattern-order bugs: last-match-wins makes line order load-bearing, and a broad glob added late silently swallows earlier specific rules. Our own `CODEOWNERS-soft` already relies on deliberate ordering (the managed-reverse-proxy block must stay last).
- Per-directory files match the mental model ("who owns _this_ directory") and scale with a monorepo, but need a coverage audit tool since nothing forces a new directory to get an owner.
- The approver/reviewer split (Kubernetes) is the single most useful role distinction: "can gate a merge" vs "should see this PR" are different sets. We already have exactly this split — hard `CODEOWNERS` vs soft — just encoded as two separate files with different formats and different consumers.
- Chromium separates approval (OWNERS) from routing metadata (DIR_METADATA: team contact, bug component). Keeping "who approves" and "who to page/ping" in one schema but different fields avoids a second file.
- Kubernetes avoids GitHub Teams for grouping (no audit trail for membership) via a PR-reviewable `OWNERS_ALIASES` file. We _do_ want GitHub team slugs (the auto-assigner needs them), but an alias layer still helps for individuals and virtual groups.
- The compile-to-CODEOWNERS pattern (structured YAML as source, flat CODEOWNERS as build artifact) is common and keeps native platform integration for free.

## 2. What the repo has today

Two data sources, one shared matcher, four consumers — all hand-maintained, three of them with their own parsers.

**Sources**

- `.github/CODEOWNERS` (58 lines): blocking. Deliberately tiny, infra/security-critical trees only ("extraordinary justification" header). Uses owner-less lines as _resets_ to clear a blocking owner for a subtree (e.g. `posthog/hogql/database/schema/**`).
- `.github/CODEOWNERS-soft` (383 lines): non-blocking review tagging. Carries all product mapping for shared code outside `products/` (~25 teams). Header already says: product-level ownership belongs in `product.yaml`; this file is for sub-folder overrides, secondary reviewers, and paths outside `products/`.
- `products/*/product.yaml` (68 files): exactly two fields, `name` and `owners` (list of team slugs, occasionally `@individual`). Owns all of `products/<name>/**` and beats any CODEOWNERS entry in the resolution used by the ownership skill.

**Consumers and their parsers**

| Consumer                                                  | Reads                      | Parser                                                                    |
| --------------------------------------------------------- | -------------------------- | ------------------------------------------------------------------------- |
| `.github/scripts/assign-reviewers.js` (CI auto-assign)    | soft + product.yaml        | vendored matcher + own YAML mini-parser                                   |
| `hogli product:lint:owners`                               | product.yaml               | own loader (`product_yaml.py`), validates slugs against live GitHub teams |
| `.agents/skills/establishing-code-ownership/ownership.js` | hard + soft + product.yaml | vendored matcher + own YAML mini-parser                                   |
| `tools/pr-approval-agent/gates.py`                        | soft only                  | fully independent reimplementation                                        |

The vendored matcher is `.github/scripts/codeowners.js` (a port of `hmarr/codeowners`, faithful to GitHub semantics).

**Gaps**

- Four parsers of the same two files; only two share the matcher. Drift is a when, not an if.
- Only `product.yaml` is CI-validated. Nothing checks that `CODEOWNERS-soft` globs still match existing files or that its team slugs exist (the assigner discovers dead teams at runtime via 422s).
- No schema for `product.yaml`; no oncall/Slack/escalation routing anywhere in the repo (handbook only).
- Consumers disagree about scope: the assigner and pr-approval-agent ignore the hard file; only the skill layers all three sources.
- No structured notion of generated/vendored/deprecated code — the assigner hardcodes an ignore list (`frontend/src/generated/**`, `*.ambr`, lockfiles, …).

## 3. Proposed canonical format: `OWNERS.yaml`

One schema, distributed per directory, plus a root alias file. Under `products/`, the existing `product.yaml` **is** the ownership file (see the alias rule below) — no new files needed there.

```yaml
# OWNERS.yaml — full form; every field except `team` is optional
version: 1

# The one required field: the responsible team. GitHub slug minus @PostHog/,
# or an alias from OWNERS_ALIASES.yaml.
team: team-error-tracking

# Non-blocking PR review tagging (defaults to [team] when omitted).
reviewers: [team-error-tracking]

# Routing metadata (Chromium DIR_METADATA role) — never affects review gates.
contact:
  slack: '#team-error-tracking'
  oncall: pagerduty:error-tracking # opaque, scheme-prefixed reference

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
    team: null # explicit reset: unowned-by-design, lint-exempt
  - match: 'migrations/**'
    reviewers: [team-error-tracking, team-data-modeling]
```

The 90% case is two lines:

```yaml
# rust/OWNERS.yaml
version: 1
team: team-ingestion
```

### `product.yaml` as an accepted alias

`products/<name>/product.yaml` with an `owners:` key is read by the resolver as if it were an `OWNERS.yaml` declaring `team: <first owner>` and `reviewers: <all owners>`. Every other field in `product.yaml` (`name:` today, anything added later) is ignored for ownership purposes — `product.yaml` remains free to grow product metadata without touching the ownership schema. Rules:

- A directory may have `product.yaml`-with-`owners` **or** `OWNERS.yaml`, never both — lint error.
- Sub-folder overrides inside a product use nested `OWNERS.yaml` as anywhere else (e.g. `products/x/backend/migrations/OWNERS.yaml`).
- The `team-CHANGEME` scaffold placeholder resolves to unowned, as all consumers already treat it.

This keeps all 68 products at zero migration cost and preserves `hogli product:lint:owners` unchanged.

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

1. Walk from the repo root toward `P`, collecting every `OWNERS.yaml` (or aliased `product.yaml`) on the way. If a file sets `inherit: false`, drop everything collected above it.
2. Effective config = shallow merge, nearest file winning per field (lists replace, never merge — predictability over cleverness).
3. Within the nearest file that has `rules:`, apply the last rule whose `match` glob (GitHub CODEOWNERS semantics, via the vendored matcher) matches `P` relative to that file's directory. Rule fields override the merged config.
4. Review tagging = resolved `reviewers`. Responsible team = resolved `team`.
5. No ownership file on the walk and no rule match → **unowned**, which fails the coverage check unless the path is under a `team: null` rule.

The hard `.github/CODEOWNERS` stays outside this walk entirely. It keeps its own GitHub-native semantics and remains hand-maintained; the resolver reads it only as a **read-only overlay** so lookups can additionally report "blocking approval required from X" (what the ownership skill layers in today). It never influences the resolved `team`/`reviewers`, and nothing in this proposal writes to it.

## 5. Tool independence: one resolver, many consumers

The stability guarantee is architectural: **consumers never parse ownership files themselves.** One resolver library owns the semantics; everything else calls it.

- **Resolver**: single implementation in `.github/scripts/owners.js` (JS, next to the vendored matcher it reuses — three of four consumers are JS and CI runs it; hard-CODEOWNERS-owned by `team-security` like its siblings). Exposes `resolve(path)`, `map()`, `unowned()` as a library, plus a CLI: `node .github/scripts/owners.js resolve --json <path...>`.
- **Non-JS consumers** shell out to the CLI and read JSON — `tools/pr-approval-agent/gates.py` replaces its private `parse_codeowners_soft`/`resolve_owners` with one subprocess call. No committed lock file, so no freshness-check machinery; if a lock file is ever wanted (offline consumers, Backstage `catalog-info.yaml` emitters), it is a trivial fold over `map()` added later.
- **Validator**: `hogli owners:lint` — schema check, team slugs against live GitHub org (reusing `product/gh.py`), alias resolution, dead `rules:` globs (match zero files), same-directory `product.yaml`/`OWNERS.yaml` conflicts, and full-tree coverage (every `git ls-files` path resolves or is `team: null`).
- **Lookup**: `hogli owners:who <path>` / `owners:team <slug>` / `owners:unowned` — thin wrappers over the CLI; the `establishing-code-ownership` skill's `ownership.js` becomes a shim over the same resolver (or is deleted in favor of it).

If the first consumer (say the auto-assigner) is ever replaced, the graph, resolver, and lint are untouched — only one caller changes. That is the "source of truth, not tool config" property.

## 6. The one PR

Everything lands atomically. The delivery order below is a review guide, not a merge sequence.

1. **Resolver + schema.** `.github/scripts/owners.js` (resolution per §4, reusing the vendored matcher), `OWNERS_ALIASES.yaml`, JSON-schema for `OWNERS.yaml`.
2. **Convert `CODEOWNERS-soft` → distributed `OWNERS.yaml`.** Mechanical translation of the 383 lines into per-directory files under `posthog/`, `frontend/src/scenes/`, `nodejs/`, `rust/`, `services/`, `ee/`, plugin-server, etc. Where the soft file relied on last-match ordering (e.g. the trailing managed-reverse-proxy block overriding a broad settings-scene rule), that intent becomes an explicit nested file or `rules:` entry — order-independence is the point.
3. **Equivalence proof.** A differ resolves every `git ls-files` path under (old: soft + product.yaml) and (new: OWNERS.yaml + product.yaml) and asserts identical reviewer sets. It runs as a test in the PR; intentional divergences (there will be a few — dead globs, stale teams the 422 fallback already skips) are listed explicitly in the PR description rather than slipping through.
4. **Flip consumers.**
   - `assign-reviewers.js`: replace soft-file parsing + `loadProductYamlRules` with the resolver. Substantive-owner thresholds, 5-team cap, comment/label behavior unchanged. Its `status: generated` handling replaces the hardcoded ignore list.
   - `gates.py`: replace the private CODEOWNERS-soft parser with the resolver CLI (`--json`).
   - `ownership.js` (skill): becomes a shim over the resolver; SKILL.md updated.
5. **Delete `.github/CODEOWNERS-soft`.** Also drop its entry from anything referencing it.
6. **Lint wiring.** `hogli owners:lint` + a CI job (extend the existing `validate-product-yamls` job rather than adding a new one). Coverage starts warn-only; ratchet to fail in a follow-up once `owners:unowned` is clean or explicitly `team: null`.

Safety properties of the atomic switch:

- `auto-assign-reviewers.yml` runs on `pull_request_target` and always checks out **master**, so the new flow activates only at merge — no half-migrated window, and in-flight unrebased PRs are unaffected (the repo's CI-backwards-compat rule holds by construction).
- The hard `CODEOWNERS` and GitHub's native enforcement are untouched, so worst case on a resolver bug is wrong _soft_ tagging, which is recoverable and non-blocking.
- The equivalence differ is the review artifact: reviewers approve a proven-identical resolution plus an explicit list of intentional diffs, not 400 lines of glob translation on faith.

## 7. Open questions for maintainers

1. **Does `contact:` (slack/oncall) belong in-repo at all,** or does it stay in the handbook/PagerDuty and the v1 schema ships without it? In-repo means one more thing to go stale; out-of-repo means the graph can't drive paging integrations. Cheap to defer — the field is optional.
2. **Individuals as owners**: support them via `OWNERS_ALIASES.yaml` only (recommended), or ban them and force team creation (`user_interviews` is the only current case)?
3. **Coverage gating cadence**: how soon after the PR to flip `owners:lint` coverage from warn to fail — immediately for _new_ directories (ratchet), or only once the whole tree is clean?
4. **Hard-CODEOWNERS future** (explicitly out of scope now): if blocking gates ever move into the schema, approver inheritance should probably union up the tree rather than nearest-wins — parked until `team-security` wants to revisit.
