---
name: stacking-prs
description: >
  Create and manage GitHub native Stacked PRs in this repo with the `gh stack` CLI.
  Use when asked to stack PRs, split a large change into a stack, add a layer to a stack,
  restack or rebase a stack, adopt existing branches or PRs into a stack, check out
  someone else's stack, or land a stack. Covers creating and submitting stacks
  (draft-first), cascade rebases with `gh stack sync`, and how to merge a stack here:
  `gh stack merge --yes --squash` for a whole stack, or `gh pr merge <n> --squash`
  one layer at a time. Squash is the only merge method this repo allows.
---

# Stacked PRs with `gh stack`

GitHub native Stacked PRs is in [public preview](https://github.blog/changelog/2026-07-30-stacked-pull-requests-are-now-in-public-preview/) and enabled on this repo.
A stack is an ordered chain of PRs where each PR targets the branch of the PR below it; the bottom PR targets `master`.
GitHub links them into a first-class stack object: the PR UI shows a stack map, branch protections (code owner approval, required checks) are enforced on **every** layer including mid-stack ones, and CI that runs on `master` PRs runs on every layer.

Setup — `gh stack merge` needs v0.1.0 or newer, so upgrade an older install:

```bash
gh extension install github/gh-stack   # or: gh extension upgrade stack
```

Upstream docs: [about stacked PRs](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs), [CLI commands](https://docs.github.com/en/pull-requests/reference/stacked-prs-cli-commands).

## Create a stack

```bash
gh stack init my-feature-db        # bottom branch, based on master
# ...commit...
gh stack add my-feature-api        # next layer, based on the previous branch
# ...commit...
gh stack add -Am "add UI" my-feature-ui   # stage all + commit in one step
```

- Adopt existing local branches (bottom to top): `gh stack init branch1 branch2 branch3`.
- Link PRs that already exist on GitHub, without local tracking: `gh stack link 41 42 43` (bottom to top; also accepts branch names and PR URLs). Pass a stack number first to append to an existing stack: `gh stack link 75391 76001`.
- Slice by reviewable unit: migration / backend / frontend, or mechanical-rename / behavior-change. Each PR must make sense to review and merge alone.
- Keep stacks shallow (2–4 layers). Every layer multiplies CI cost and rebase churn, and deep-stack pushes can trip GitHub's dispatch cap (see AGENTS.md, "Stacked PRs").

## Publish

```bash
gh stack submit --auto
```

Pushes all branches, creates each PR with the correct base, and links the stack on GitHub.
`--auto` creates new PRs **as drafts**, the right default here, since drafts run the narrowed CI matrix.
Mark layers ready individually with `gh pr ready <n>`, or pass `--open` to mark everything ready.
Running `gh stack submit` with no flags opens an interactive editor for titles and descriptions instead; in that editor new PRs default to ready-for-review, so flip the "CREATE AS" toggle if you want drafts.

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
- The `ci:preflight` pre-push hook runs on these pushes like any other; never bypass it.

## Merging

Squash is the only merge method this repo allows, and the Trunk merge queue is paused (see AGENTS.md, "Merging PRs"), so a stack merges directly.
Branch protection still applies to every layer: approving review, code owner review, required checks, signed commits. GitHub evaluates all of it when the merge runs, and rule bypass is not supported for stacks.

Land the whole stack in one operation once every layer is approved and green:

```bash
gh stack merge --yes --squash            # current stack
gh stack merge <pr-number> --yes --squash   # everything up to and including that PR
```

Merging any PR also merges every unmerged PR below it. You cannot land a mid-stack layer on its own, so don't reach for `gh stack merge` until the layers underneath are reviewed too.

To land one layer at a time instead, merge the bottom PR the normal way:

```bash
gh pr merge <n> --squash
```

Either way, once a layer lands GitHub retargets the next PR onto `master` and updates the stack. Run `gh stack sync --prune` to replay the remaining layers onto the squashed commit and drop the merged local branch.

Auto-merge is not supported for stacked PRs, so `--auto` won't help you here.

If the Trunk queue is re-enabled, `gh stack merge` routes onto the queue instead of merging directly, and the usual queue rule applies: never `gh stack sync`, `rebase`, or `push` while a layer sits in it, since the force-push kicks it out. `gh stack push` skips branches queued in _GitHub's_ merge queue, but it knows nothing about Trunk's.

## Scripting

- List stacks: `gh api repos/{owner}/{repo}/stacks`; one stack: `.../stacks/<stack-number>`. Stack numbers come from the same sequence as PR numbers, so they never collide.
- Local stack state: `gh stack view --json`.

## Limits (preview)

All branches must live in the same repository (no cross-fork stacks), the chain must be strictly linear (no branching structures, and every layer must be rebased before it can merge), auto-merge is unsupported, and GitHub Desktop doesn't support stacks.
