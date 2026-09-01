# .stamphog

Declarative policy for the stamphog PR-approval merge gate (`products/stamphog/packages/pr-approval-agent/`).
The engine loads these files from the checked-out working tree at run time.
Engine and policy are vendored into other repos (see the note in the engine's README), so format changes here need those copies re-synced too.

## What lives here

- `policy.yml` - the global machine policy: deny categories, allow-list, size gate, tier thresholds, dismiss-time triviality rules, the folder delegation contract, and the ownership source (the `hogli-resolver` input that feeds the reviewer's advisory team context via the shared hogli resolver). Trusted data. Each rule's `rationale` records why the rule became what it is (which false positives drove an exclusion, and when) - historical justification like a commit message, not a claim about the present.
- `review-guidance.md` - the trusted review-norms prose injected into the reviewer's system prompt. Ordinary repo-formatted markdown. Editing it changes the production prompt directly, so update deliberately - the `stamphog_policy` deny guarantees a human reviews every change.

## Proposing a policy change

Open a PR that edits these files.
Stamphog can never auto-approve it: the `stamphog_policy` deny category matches `.stamphog/**`, any `AGENT_APPROVALS.md`, and any `pr-approval-agent/**`, so every change to the gate's own policy or engine routes to a human reviewer.
The loader also hard-fails if that self-governance entry is ever missing, so it cannot be dropped silently.

## Per-folder overrides (`AGENT_APPROVALS.md`)

A folder may carry an `AGENT_APPROVALS.md` with a `stamphog:` frontmatter block plus advisory prose.
Resolution:

- Every `AGENT_APPROVALS.md` at or above a changed file governs it: guidance accumulates outermost first, and a child file adds to its ancestors rather than replacing them.
- For the delegated `size_gate.max_files` and `size_gate.max_lines`, the nearest file on the chain with a valid grant wins for its files (within the contract ceilings). Each key resolves on its own: a folder that grants only one key leaves its files to the nearest ancestor grant of the other key, or to the global pool when no ancestor grants it. Files whose chain grants nothing belong to the global pool.
- The frontmatter is a positive allow-list: only keys named in the `overrides` contract in `policy.yml` are read, within their ceilings. Anything else (unknown key, out-of-bounds value, unparseable frontmatter) invalidates the whole file - frontmatter and prose. An invalid file contributes nothing itself, but it does not cancel its ancestors: files under it still ride an ancestor's grant, or fall to the global pool if the chain grants nothing. Rationale: an author who can write an invalid file could equally delete it, so treating invalid as absent grants no extra power, and every `AGENT_APPROVALS.md` edit is human-reviewed via the `stamphog_policy` deny anyway.
- The prose is untrusted advisory guidance. It is sanitized, length-capped, and injected inside the reviewer prompt's untrusted region; it can never override the deny rules or the refusal criteria.

### Mixed PRs get mixed leniency

Each scope's files are counted against that scope's own ceiling, so a grant covers exactly the files that resolve to it (the nearest valid grant of that key on their chain) and nothing else.
Example: a PR changing 30 files under `products/visual_review/` (ceiling 50) plus 19 files elsewhere (global ceiling 20) passes, because each budget fits.
Add a 21st global file and the PR is denied for the global budget, no matter how much headroom the folder still has.
Files whose chain grants nothing (no folder file, prose-only, or only invalid grants) count against the global budget, so splitting files across pseudo-scopes can never inflate the allowance.
Lines follow the same rule: a scope's substantive lines are counted against that scope's own line ceiling, and the global pool's lines against the global line ceiling.
The two ceilings are budgeted separately, so a folder that raises only the line ceiling still counts its files against the one global file budget.
That keeps a one-key grant from opening a second budget for the key it never asked for.

### The roof bounds the whole PR

Per-scope budgets alone would let a PR's total grow with the number of scopes it touches.
A folder granting 1000 lines next to the 800-line global pool would allow 1800, and every further granting folder would add its own budget on top.
So each ceiling also carries a roof over the whole PR: the most generous ceiling in play for that key.
A PR touching `products/desktop/` gets a 1000-line roof, whatever else it touches.

The roof needs no separate number in `policy.yml`.
Every grant is validated at or under the contract ceiling, and the global pool is always a scope, so the roof stays between the global default and the contract ceiling.
With no grant in play it equals the global default, which is the single global total the gate applied before the ceilings became delegable.

The roof takes no headroom away from a scope.
The per-scope budgets still hold, so the extra lines a folder's grant unlocks are only spendable inside that folder.

## Delegation contract

The set of keys a folder file may override lives under `overrides` in `policy.yml` (currently `size_gate.max_files`, ceiling 50, and `size_gate.max_lines`, ceiling 1000).
A ceiling therefore bounds two things: the largest value a folder may grant, and the highest a PR's roof can ever go for that key.
It is not the limit every PR gets. A PR whose files reach no grant keeps the lower global roof.
The loader rejects a ceiling under its own global default, which would otherwise bound nothing.
deny, allow, dismiss, and tiers are non-delegable by construction - they are absent from the contract and cannot be granted from a folder file.
