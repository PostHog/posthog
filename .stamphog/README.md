# .stamphog

Declarative policy for the stamphog PR-approval merge gate (`tools/pr-approval-agent/`).
The engine loads these files from the checked-out working tree at run time.

## What lives here

- `policy.yml` - the global machine policy: deny categories, allow-list, size gate, tier thresholds, dismiss-time triviality rules, and the folder delegation contract. Trusted data. Each rule's `rationale` records why the rule became what it is (which false positives drove an exclusion, and when) - historical justification like a commit message, not a claim about the present.
- `review-guidance.md` - the trusted review-norms prose injected into the reviewer's system prompt. Ordinary repo-formatted markdown. Editing it changes the production prompt directly, so update deliberately - the `stamphog_policy` deny guarantees a human reviews every change.

## Proposing a policy change

Open a PR that edits these files.
Stamphog can never auto-approve it: the `stamphog_policy` deny category matches `.stamphog/**`, any `AGENT_POLICIES.md`, and `tools/pr-approval-agent/**`, so every change to the gate's own policy or engine routes to a human reviewer.
The loader also hard-fails if that self-governance entry is ever missing, so it cannot be dropped silently.

## Per-folder overrides (`AGENT_POLICIES.md`)

A folder may carry an `AGENT_POLICIES.md` with a `stamphog:` frontmatter block plus advisory prose.
Resolution:

- Every changed file is governed by the nearest `AGENT_POLICIES.md` at or above it; files without one belong to the global pool.
- The frontmatter is a positive allow-list: only keys named in the `overrides` contract in `policy.yml` are read, within their ceilings. Anything else (unknown key, out-of-bounds value, unparseable frontmatter) invalidates the whole file - frontmatter and prose - and its files fall back to the global pool.
- The prose is untrusted advisory guidance. It is sanitized, length-capped, and injected inside the reviewer prompt's untrusted region; it can never override the deny rules or the refusal criteria.

### Mixed PRs get mixed leniency

Each scope's files are counted against that scope's own file ceiling, so a folder's grant covers exactly its own files and nothing else.
Example: a PR changing 30 files under `products/visual_review/` (ceiling 50) plus 19 files elsewhere (global ceiling 20) passes, because each budget fits.
Add a 21st global file and the PR is denied for the global budget, no matter how much headroom the folder still has.
Files under a prose-only or invalid folder file count against the global budget too, so splitting files across pseudo-scopes can never inflate the allowance.
The line ceiling stays a single global total; it is not delegable.

## Delegation contract

The set of keys a folder file may override lives under `overrides` in `policy.yml` (currently just `size_gate.max_files`, ceiling 50).
deny, allow, dismiss, tiers, and `size_gate.max_lines` are non-delegable by construction - they are absent from the contract and cannot be granted from a folder file.
