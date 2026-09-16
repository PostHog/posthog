# Stamphog repo configuration

Optional per-repository configuration for [stamphog](https://github.com/PostHog/posthog/tree/master/products/stamphog), the approve-first PR reviewer.

Nothing here is required.
A repository with no `.stamphog/` directory reviews under the hosted defaults that the stamphog server ships.
Every file below is read from the repository's **default branch**, never from the PR head, so a pull request cannot rewrite the policy that gates it.
The server overwrites the sandbox checkout's `.stamphog/` with the default-branch versions after the clone.

This repository's own files are the worked example for each section.

## `policy.yml`

The machine policy: deny categories, allow-list, size gate, tier thresholds, the folder delegation contract, the author-familiarity signal, and the ownership source that feeds the reviewer's advisory team context.
Trusted data.

The file is a **section overlay** onto the hosted default.
Declare only the top-level sections you want to change, and each section you declare replaces the default's section wholesale.
A repository that only wants a bigger size gate writes five lines:

```yaml
version: 1
size_gate:
  max_lines: 1200
  max_files: 40
```

Everything else, including every deny category, still comes from the hosted default.

The merged document is validated by the engine's strict loader inside the sandbox.
Required sections and the `stamphog_policy` self-governance deny therefore cannot be dropped by omission.
A file that is present but unusable, such as malformed YAML or a non-mapping root, fails the run closed: the repository declared something, so reviewing under pure defaults would be wrong.

Each rule may carry a `rationale`.
It records why the rule became what it is, which false positives drove an exclusion and when.
Treat it as historical justification like a commit message, not as a claim about the present.

### The `digest:` key

`policy.yml` also carries an optional `digest:` section.
It names a single Slack channel for all of the repository's merged-PR digests, which opts the repository out of the audience cascade:

```yaml
digest:
  channel: '#my-team'
```

The review engine tolerates and ignores this key.
Only the digest reads it.

### Self-governance

The `stamphog_policy` deny category matches `.stamphog/**`, any `AGENT_APPROVALS.md`, and any `pr-approval-agent/**`.
So stamphog can never auto-approve a change to its own policy or engine.
The loader hard-fails if that entry is ever missing, so it cannot be dropped silently.

## `review-guidance.md`

The trusted review-norms prose injected into the reviewer's system prompt.
Ordinary repo-formatted markdown.

When present, it replaces the hosted default norms wholesale.
Editing it changes the production prompt directly, so update it deliberately.
The `stamphog_policy` deny guarantees a human reviews every change.

## `steering.md`

Optional advisory guidance from the repository's maintainers.
There is no hosted default: an absent file leaves the reviewer prompt unchanged.

When present, it is appended to the review guidance under a marked "Repository-specific steering" section.
Use it to add repository-specific norms without replacing the whole guidance file.
It is trusted default-branch content, the same as the other files here.

## `AGENT_APPROVALS.md`

A folder anywhere in the repository may carry an `AGENT_APPROVALS.md` with a `stamphog:` frontmatter block plus advisory prose.

Resolution:

- Every `AGENT_APPROVALS.md` at or above a changed file governs it.
  Guidance accumulates outermost first, and a child file adds to its ancestors rather than replacing them.
- For the delegated `size_gate.max_files` and `size_gate.max_lines`, the nearest file on the chain with a valid grant wins for its files, within the contract ceilings.
  Each key resolves on its own.
  A folder that grants only one key leaves its files to the nearest ancestor grant of the other key, or to the global pool when no ancestor grants it.
  Files whose chain grants nothing belong to the global pool.
- The frontmatter is a positive allow-list.
  Only keys named in the `overrides` contract in `policy.yml` are read, within their ceilings.
  Anything else invalidates the whole file, frontmatter and prose: an unknown key, an out-of-bounds value, or unparseable frontmatter.
  An invalid file contributes nothing itself, but it does not cancel its ancestors.
  Files under it still ride an ancestor's grant, or fall to the global pool if the chain grants nothing.
  Treating invalid as absent grants no extra power, because an author who can write an invalid file could equally delete it, and every `AGENT_APPROVALS.md` edit is human-reviewed anyway.
- The prose is untrusted advisory guidance.
  It is sanitized, length-capped, and injected inside the reviewer prompt's untrusted region.
  It can never override the deny rules or the refusal criteria.

### Mixed PRs get mixed leniency

Each scope's files are counted against that scope's own ceiling.
A grant covers exactly the files that resolve to it, which is the nearest valid grant of that key on their chain, and nothing else.

Example: a PR changing 30 files under `products/visual_review/` (ceiling 50) plus 19 files elsewhere (global ceiling 20) passes, because each budget fits.
Add a 21st global file and the PR is denied for the global budget, however much headroom the folder still has.

Files whose chain grants nothing count against the global budget, so splitting files across pseudo-scopes can never inflate the allowance.
That covers a missing folder file, a prose-only file, and a file with only invalid grants.
Lines follow the same rule: a scope's substantive lines count against that scope's own line ceiling, and the global pool's lines against the global line ceiling.
The two ceilings are budgeted separately.
A folder that raises only the line ceiling still counts its files against the one global file budget, which keeps a one-key grant from opening a second budget for the key it never asked for.

### The roof bounds the whole PR

Per-scope budgets alone would let a PR's total grow with the number of scopes it touches.
A folder granting 1000 lines next to the 800-line global pool would allow 1800, and every further granting folder would add its own budget on top.
So each ceiling also carries a roof over the whole PR: the most generous ceiling in play for that key.
A PR touching `products/desktop/` gets a 1000-line roof, whatever else it touches.

The roof needs no separate number in `policy.yml`.
Every grant is validated at or under the contract ceiling, and the global pool is always a scope, so the roof stays between the global default and the contract ceiling.
With no grant in play it equals the global default, which is the single global total the gate applies to an unmodified policy.

The roof takes no headroom away from a scope.
The per-scope budgets still hold, so the extra lines a folder's grant unlocks are only spendable inside that folder.

### Delegation contract

The set of keys a folder file may override lives under `overrides` in `policy.yml`.
In this repository that is `size_gate.max_files`, ceiling 50, and `size_gate.max_lines`, ceiling 1000.

A ceiling bounds two things: the largest value a folder may grant, and the highest a PR's roof can ever go for that key.
It is not the limit every PR gets.
A PR whose files reach no grant keeps the lower global roof.
The loader rejects a ceiling under its own global default, which would otherwise bound nothing.

`deny`, `allow`, `dismiss` and `tiers` are non-delegable by construction.
They are absent from the contract and cannot be granted from a folder file.

## Proposing a change

Open a PR that edits these files.
Stamphog can never auto-approve it: the `stamphog_policy` deny category routes every change to the gate's own policy or engine to a human reviewer.
The loader also hard-fails if that self-governance entry is ever missing, so it cannot be dropped silently.
