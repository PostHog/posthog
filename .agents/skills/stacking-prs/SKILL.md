---
name: stacking-prs
description: >
  Create and manage GitHub native Stacked PRs in this repo with the `gh stack` CLI.
  Use when asked to stack PRs, split a large change into a stack, add a layer to a stack,
  restack or rebase a stack, adopt existing branches or PRs into a stack, check out
  someone else's stack, or land a stack. Covers creating and submitting stacks
  (draft-first), cascade rebases with `gh stack sync`, and landing one through the
  Trunk merge queue via `/merging-prs` — whole-stack via `/trunk merge` on the top
  layer, or bottom-first — never `gh stack merge`.
---

# Stacked PRs with `gh stack`

GitHub's native stacked PRs are enabled on this repo.
A stack is an ordered chain of PRs where each one targets the branch of the PR below it; the bottom PR targets `master`.
GitHub tracks the chain as a first-class object: the PR UI shows a stack map, branch protections (code owner approval, required checks) apply to **every** layer including mid-stack ones, and CI that runs on `master` PRs runs on every layer.

Setup (this skill is written against `gh-stack` v0.1.0):

```bash
gh extension install github/gh-stack   # or: gh extension upgrade stack
```

Upstream docs: [about stacked PRs](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs), [CLI commands](https://docs.github.com/en/pull-requests/reference/stacked-prs-cli-commands).

## In a cloud task sandbox, use `gh_stack` instead

The rest of this skill assumes a developer machine.
Cloud task runs block `git commit` and `git push` so unsigned commits cannot leave the sandbox, which takes out every `gh stack` command that publishes a stack — `submit`, `sync`, `push`, and `link` with branch arguments all push, and `gh stack add -m` commits.

There, build the stack from the signed-commit tooling and link it with the `gh_stack` MCP tool, which drives GitHub's Stacks REST API and never pushes:

1. Commit each layer with `git_signed_commit`, passing a new `branch` — the checkout already sits on the layer below, so the branch starts there.
2. Open each layer's PR with `gh pr create --base <branch of the layer below>`.
3. Link them with `gh_stack`, operation `create`, passing `pull_requests` bottom to top.

To restack a layer: check that layer out, `git rebase <its parent branch>`, then republish it with `git_signed_rewrite` passing `onto` = the parent branch.
`gh stack rebase` still does the rebase itself, but nothing may publish the result — `gh stack push` and `gh stack sync` both push.
`git_signed_rewrite` replays whatever local HEAD points at and uses `branch` only to pick which remote ref moves, so the layer has to be the checked-out branch or you publish the wrong history to it.

## Create a stack

```bash
gh stack init my-feature-db        # bottom branch, based on master
# ...commit...
gh stack add my-feature-api        # next layer, based on the previous branch
# ...commit...
gh stack add -Am "add UI" my-feature-ui   # stage all + commit in one step
```

- Adopt existing local branches (bottom to top): `gh stack init branch1 branch2 branch3`.
- Link PRs that already exist on GitHub, without local tracking: `gh stack link <pr> <pr> <pr>`, bottom to top (branch names and PR URLs work too). Pass a stack number first to append to an existing stack: `gh stack link <stack> <pr>`.
- Slice by reviewable unit: migration / backend / frontend, or mechanical-rename / behavior-change. Each PR must make sense to review and merge alone.
- Keep stacks shallow (2–4 layers). Every layer multiplies CI cost and rebase churn, and deep-stack pushes can trip GitHub's dispatch cap (see AGENTS.md, "Stacked PRs").

## Publish

```bash
gh stack submit --auto
```

Pushes all branches, creates each PR with the correct base, and links the stack on GitHub.
`--auto` creates new PRs **as drafts**, the right default here, since drafts run the narrowed CI matrix.
Mark layers ready individually with `gh pr ready <n>`, or pass `--open` to mark everything ready.
Running `gh stack submit` with no flags opens an interactive editor for titles and descriptions instead.
New PRs default to ready-for-review in that editor, so flip its "CREATE AS" toggle if you want drafts.

Each layer is a normal PR: it needs a conventional-commit title and a description filled from `.github/pull_request_template.md`.

## Iterate and keep in sync

```bash
gh stack sync            # fetch, cascade-rebase onto master and each parent, force-with-lease push, sync PR state
gh stack sync --prune    # also delete local branches for merged PRs
```

- To fix a mid-stack layer: check out that branch (`gh stack down` / `gh stack switch`), commit, then `gh stack sync` (or `gh stack rebase --upstack` to rebase only the layers above you, `--no-trunk` to skip pulling master).
- On rebase conflict, sync restores all branches untouched; run `gh stack rebase`, resolve, then `gh stack rebase --continue` (or `--abort`).
- `gh stack view --short` shows status (`--json` for scripting); a `⚠` means that layer needs a rebase, which blocks merging. `gh stack checkout <stack-number|PR|URL>` pulls down and tracks a stack you don't have locally, including a teammate's.
- `gh stack modify` interactively reorders, folds, drops, or renames layers. `gh stack unstack` removes the stack on GitHub (`--local` to only drop local tracking).
- Batch work before syncing. Each sync force-pushes and re-runs a full CI matrix for every rebased layer, so sync when you need the rebase, not to track master.
- Layer branches move without you: ReviewHog and other bots push fix commits straight onto PR branches. `gh stack sync` fetches first and pushes with `--force-with-lease`, so it refuses when a branch moved; treat that refusal as "someone committed here, go read it", not "retry". Before any manual `git push` or rebase of a layer, `git fetch origin` and fast-forward onto the remote head. Never plain force-push a layer branch.
- The `ci:preflight` pre-push hook runs on these pushes like any other; never bypass it.

## Merging

Both paths go through the Trunk merge queue via `/merging-prs`; never `gh stack merge`, which merges the chain through GitHub's API and bypasses the queue. An agent must obtain explicit user approval in the current conversation for the identified stack before enqueueing, re-enqueueing, or otherwise causing any layer to land.

**Whole stack at once (default).**
The queue handles stacks natively: enqueueing a PR enqueues it and every unmerged layer below it, tests them together, and merges them atomically.
After explicit user approval, comment `/trunk merge` on the **top** PR to land the whole stack, or on the highest layer that's ready to land just the bottom part.
Every layer being merged must individually pass `/merging-prs` preflight (ready, approved, no failing checks — pending ones are fine, the queue waits for them) — a mid-stack draft or missing approval blocks the layers above it.

**Bottom-first, one layer at a time.**
After explicit user approval, merge the layer based on `master` via `/merging-prs`, exactly as you would an unstacked PR.
GitHub then retargets the next layer onto `master` and updates the stack.

After either path:

```bash
gh stack sync --prune   # replay the remaining layers onto the squashed commit(s), drop merged branches
```

Do **not** use `gh stack merge`.
It merges the whole chain straight through GitHub's API, so the bottom layer reaches `master` outside the path AGENTS.md requires ("Merging PRs").
Merging any layer also merges every unmerged layer below it, so a mid-stack merge is only safe once those layers are reviewed and green.

Every layer is gated on its own approving review, code owner review, required checks, and signed commits.
Rule bypass and auto-merge are both unsupported for stacks, so `--auto` won't help you here.

Never `gh stack sync`, `rebase`, or `push` while a layer sits in the merge queue; the force-push kicks it out.
`gh stack push` knows to skip branches queued in _GitHub's_ merge queue, but it can't see Trunk's.

## Scripting

- List stacks: `gh api repos/{owner}/{repo}/stacks`; one stack: `.../stacks/<stack-number>`. Stack numbers come from the same sequence as PR numbers, so they never collide.
- Local stack state: `gh stack view --json`.

## Limits

All branches must live in the same repository (no cross-fork stacks), and the chain must be strictly linear: no branching structures, and every layer needs a rebase before it can merge.
GitHub Desktop doesn't support stacks at all.
These are preview-era constraints, so check the [upstream docs](https://docs.github.com/en/pull-requests/reference/stacked-prs-cli-commands) before concluding something is impossible.
