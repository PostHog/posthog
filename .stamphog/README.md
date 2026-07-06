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

- Overrides apply to a PR only when the nearest such file sits at or above the common ancestor of every changed file. This walks up from the deepest shared directory of the PR's files.
- The frontmatter is a positive allow-list: only keys named in the `overrides` contract in `policy.yml` are read, within their ceilings. Anything else (unknown key, out-of-bounds value, unparseable frontmatter) invalidates the whole file - frontmatter and prose - and the strict global policy applies.
- The prose is untrusted advisory guidance. It is sanitized, length-capped, and injected inside the reviewer prompt's untrusted region; it can never override the deny rules or the refusal criteria.

### The stray-file gotcha

Because resolution keys off the common ancestor, one stray file outside the folder disables the override.
Example: a PR touching only `products/visual_review/*` resolves to `products/visual_review/AGENT_POLICIES.md` and gets its higher file ceiling.
Add a single root-level file (say a top-level `README.md`) and the common ancestor collapses to the repo root, where no override applies, so the strict global ceiling is used.
The fail direction is always stricter.

## Delegation contract

The set of keys a folder file may override lives under `overrides` in `policy.yml` (currently just `size_gate.max_files`, ceiling 50).
deny, allow, dismiss, tiers, and `size_gate.max_lines` are non-delegable by construction - they are absent from the contract and cannot be granted from a folder file.
