---
name: stacking-prs
description: >
  Create and manage GitHub native Stacked PRs in this repo with the `gh stack` CLI.
  Use when asked to stack PRs, split a large change into a stack, add a layer to a stack,
  restack or rebase a stack, adopt existing branches or PRs into a stack, check out
  someone else's stack, or land a stack. Covers creating and submitting stacks
  (draft-first), cascade rebases with `gh stack sync`, and the Trunk-queue merge flow.
  Never use `gh stack merge` here — all merges go through the Trunk merge queue,
  bottom-up, one PR at a time.
---

# Stacked PRs with `gh stack`

GitHub native Stacked PRs (private preview) is **enabled on this repo**.
A stack is an ordered chain of PRs where each PR targets the branch of the PR below it; the bottom PR targets `master`.
GitHub links them into a first-class stack object: the PR UI shows a stack map, and every layer's branch protections are evaluated against the final target (`master`), not its direct base.

One-time setup:

```bash
gh extension install github/gh-stack
```

## Create a stack

```bash
gh stack init my-feature-db        # bottom branch, based on master
# ...commit...
gh stack add my-feature-api        # next layer, based on the previous branch
# ...commit...
gh stack add -Am "add UI" my-feature-ui   # stage all + commit in one step
```

- Adopt existing local branches (bottom to top): `gh stack init branch1 branch2 branch3`.
- Link PRs that already exist on GitHub, without local tracking: `gh stack link 41 42 43` (bottom to top; also accepts branch names and PR URLs).
- Slice by reviewable unit — migration / backend / frontend, or mechanical-rename / behavior-change. Each PR must make sense to review and merge alone.
- Keep stacks shallow (2–4 layers). Every layer multiplies CI cost and rebase churn, and deep-stack pushes can trip GitHub's dispatch cap (see AGENTS.md, "Stacked PRs").

## Publish

```bash
gh stack submit --auto
```

Pushes all branches, creates each PR with the correct base, and links the stack on GitHub.
`--auto` creates new PRs **as drafts** — the right default here, since drafts run the narrowed CI matrix.
Mark layers ready individually with `gh pr ready <n>`, or pass `--open` to create/mark everything ready.
Interactive `gh stack submit` (no flags) opens an editor for titles/descriptions; note its new-PR default is ready-for-review, not draft.

## Iterate and keep in sync

```bash
gh stack sync            # fetch, cascade-rebase onto master and each parent, force-with-lease push, sync PR state
gh stack sync --prune    # also delete local branches for merged PRs
```

- To fix a mid-stack layer: check out that branch (`gh stack down` / `gh stack switch`), commit, then `gh stack sync` (or `gh stack rebase --upstack` to rebase only the layers above you, without pulling trunk).
- On rebase conflict, sync restores all branches untouched; run `gh stack rebase`, resolve, then `gh stack rebase --continue` (or `--abort`).
- `gh stack view --short` shows status (`--json` for scripting); `gh stack checkout <stack-number|PR|URL>` pulls down and tracks a stack you don't have locally, including a teammate's.
- `gh stack modify` interactively reorders, folds, drops, or renames layers.
- Batch work before syncing: every sync force-pushes every rebased branch, and each push dispatches a full CI matrix per layer. Don't re-sync on every master change — sync when you need the rebase, not to stay perfectly current.
- The `ci:preflight` pre-push hook runs on these pushes like any other; never bypass it.

## Merging: Trunk queue only, bottom-up

**Never run `gh stack merge`.**
It uses GitHub's direct/atomic stack merge (or GitHub's merge queue), both blocked by branch ruleset — this repo merges exclusively through the Trunk merge queue (`/merging-prs`).

Land one layer at a time, from the bottom:

1. Mark the bottom PR ready, get review, enqueue with `gh pr comment <n> --body "/trunk merge"`, and babysit it per `/merging-prs`.
2. **While any PR of the stack is in the Trunk queue, do not run `gh stack sync`, `rebase`, or `push`** — the force-push kicks it out of the queue. `gh stack push` auto-skips only branches queued in _GitHub's_ merge queue; it knows nothing about Trunk's, so it will happily force-push a Trunk-queued branch.
3. After it merges, GitHub retargets the next PR to `master` and updates the stack. Run `gh stack sync` — it replays the remaining layers onto the squashed master commit without artificial conflicts (`--prune` to drop the merged local branch).
4. Repeat with the new bottom PR.

## Scripting

- List stacks: `gh api repos/{owner}/{repo}/stacks`; one stack: `.../stacks/<stack-number>`. Stack numbers are allocated from the same sequence as PR numbers, so they never collide.
- Local stack state: `gh stack view --json`.

## Limits (preview)

Linear history required; max 100 PRs per stack; no cross-fork stacks; rule bypass and auto-merge unsupported (irrelevant here — Trunk is the only merge path).
