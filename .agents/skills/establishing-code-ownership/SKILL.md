---
name: establishing-code-ownership
description: Determine which PostHog team owns a file, directory, or code path, or enumerate all code a team owns (via distributed `owners.yaml`, `products/*/product.yaml`, and `.github/CODEOWNERS`). Use when assigning a reviewer, attributing a bug or slow query to a team, routing work, scoping a team-wide audit, or answering "who owns X" / "what does team Y own".
---

# Establishing code ownership

Ownership is resolved by one tool — `hogli owners:*` — over distributed `owners.yaml` files.
Don't re-parse the ownership files by hand; the resolver owns the semantics and is what CI enforces.

## Fast path: `hogli owners:*`

Dev machines have flox/hogli, so shell straight to the resolver.

```bash
hogli owners:who posthog/hogql/printer.py    # who owns this path (+ the file that decided it)
hogli owners:resolve --json posthog/api/survey.py products/surveys/backend/api.py   # batch, JSON keyed by path
hogli owners:unowned                          # every tracked file with no owner (append a prefix to scope: `owners:unowned products/`)
```

`owners:who` prints the resolved `owners`, the `status`, the derived Slack channel, and `source` — the `owners.yaml`/`product.yaml` file that decided the answer.
`owners:resolve` takes paths as arguments or newline-delimited on stdin, so you can pipe a file list: `git ls-files posthog/hogql | hogli owners:resolve --json`.
No hogli/flox available? The dependency-light fallback needs only pyyaml: `git ls-files posthog/hogql | PYTHONPATH=tools/hogli-commands python -m hogli_commands.owners` (stdin paths → the same JSON).

## Resolution algorithm (what the resolver does)

For a path, it walks from the repo root down to the path collecting ownership files, then merges them **nearest-file-wins**:

1. **`owners.yaml` — the canonical, distributed source.** Each directory can carry one. Fields (`owners`, `contact`, `status`, `inherit`, per-path `rules`) fall through to the nearest ancestor unless overridden. `inherit: false` cuts the walk (Gerrit's `set noparent`) — nothing above it contributes. Within a file, `rules:` are last-match-wins. `owners: null` means **unowned by design** (exempt from the coverage check), distinct from a directory with no file at all (genuinely unowned).
2. **`products/<name>/product.yaml` — an accepted alias.** When a product dir has no `owners.yaml`, its `product.yaml` `owners:` list is read as the ownership for `products/<name>/**` (every other `product.yaml` field is ignored). A dir with both files is a lint error; `owners.yaml` wins.
3. **`.github/CODEOWNERS` — blocking approvals, never part of the walk.** It keeps GitHub-native semantics, stays hand-maintained (mostly infra, e.g. `team-security`), and is enforced by GitHub itself. The resolver does **not** read it — when you need to know whether a blocking approval is additionally required, consult the file directly. It never changes the resolved `owners`, and nothing here writes to it.

Owners are a mixed list of **team slugs** (`team-devex`, `conversations`, `logs` — the GitHub team handle minus `@PostHog/`) and **`@handles`** for individuals; the first entry is the primary owner.

## team → code (what does this team own?)

There's no single "team → files" command; resolve the tree and filter by slug:

```bash
git ls-files | hogli owners:resolve --json | jq -r 'to_entries[] | select(.value.owners | index("team-surveys")) | .key'
```

Also grep `products/*/product.yaml` for the slug — each hit is all of that `products/<name>/**`; one team often owns several, so don't stop at the first.
Owned paths span backend **and** `frontend/src/...`; cover both, or say up front you're doing one side.

## Generated files

A generated artifact often resolves to a broad parent owner or nobody.
Trace it to the input it's generated from and report **that** team as the logical owner (e.g. `services/mcp/src/tools/generated/<x>.ts` comes from `products/<name>/mcp/tools.yaml`).
Distinguish the logical owner (the team owning the source — the answer to report) from the literal resolver result on the generated path, and flag the gap so the operator can decide whether to pin it with a `rules:` entry.

## Last resort: feature-ownership handbook, then Slack

If neither the resolver nor `product.yaml` resolves it, consult the [feature-ownership handbook](https://posthog.com/handbook/engineering/feature-ownership) — coarse-grained (broad areas, not files) and hand-maintained, so prefer the repo files and flag any handbook-sourced answer as possibly stale.
If even that fails and the Slack MCP is available, search Slack — least authoritative (opinions, stale threads), so verify against the repo files and flag the answer as Slack-sourced.

## Slug vs handle

- **Handle** (`CODEOWNERS`): `@PostHog/<slug>`, e.g. `@PostHog/team-replay`.
- **Slug** (`owners.yaml` / `product.yaml`): handle minus `@PostHog/`, e.g. `team-replay`.
- **Not uniform**: some carry `team-` (`team-self-driving`), some don't (`conversations`, `logs`). If a name doesn't resolve, try both forms.
