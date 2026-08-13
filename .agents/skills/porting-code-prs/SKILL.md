---
name: porting-code-prs
description: >
  Recreate open PostHog/code pull requests as PostHog/posthog PRs against the imported
  products/desktop/ tree, preserving commit authorship. Use when asked to port, remake,
  migrate or recreate PostHog/code PRs onto the monorepo after the desktop import, whether
  a single PR or a sweep of everything an author has open. Covers enumerating an author's
  open PRs, applying the patch series with git am --directory, the 3-way fallback via
  fetching the source PR head, the paths that must never be blind-applied (.github
  workflows, lockfiles, drift-listed local patches), verification from products/desktop/
  and opening the monorepo PR with original attribution. Trigger terms: PostHog/code,
  code repo PRs, desktop migration, port my PRs, remake PRs onto the monorepo.
---

# Porting PostHog/code PRs to the monorepo

PostHog/code's `main` is frozen after the desktop import.
The tree lives at `products/desktop/` as a verbatim copy of the source at a pinned SHA, so open PRs on PostHog/code can no longer land there and are remade as monorepo PRs instead.
[`products/desktop/MIGRATION.md`](../../../products/desktop/MIGRATION.md) is the contract for the import: its pinned SHA, drift list and workflow mapping table are authoritative over anything restated here. Read it before resolving any conflict.

Path mapping: `<path>` in PostHog/code becomes `products/desktop/<path>`.
The one exception is `.github/`, which was not imported: source workflows were transformed into root `.github/workflows/desktop-*.yml` files per the mapping table and transform rules in MIGRATION.md.

## Scope the sweep

Resolve the author's GitHub login first (`gh api user --jq .login` when it is the requester). Then enumerate:

```sh
gh pr list --repo PostHog/code --author <login> --state open \
  --json number,title,isDraft,headRefName,url,body
```

For each PR decide: port, skip or flag.

- Skip a PR whose change already exists in `products/desktop/` (superseded, or landed upstream and arrived via a resync). Check the tree, not just the PR state.
- Never port a PR that was merged into PostHog/code. Merged-after-pin changes arrive through the resync protocol in MIGRATION.md, and porting them too would duplicate the diff.
- When source PRs stack on each other, port in dependency order and stack the monorepo branches the same way.

The skill works the same for a single PR; the sweep is just the loop.

## Port one PR

Work on a branch off fresh `master`, one monorepo PR per source PR. Reusing the source head branch name keeps the pair easy to correlate.

1. Fetch the patch series, plus the source objects the 3-way fallback needs:

```sh
PATCH=$(mktemp)
gh pr diff <N> --repo PostHog/code --patch > "$PATCH"
git fetch https://github.com/PostHog/code.git refs/pull/<N>/head
```

2. Apply with authorship preserved:

```sh
git am -3 --empty=drop --directory=products/desktop/ \
  --exclude='products/desktop/.github/*' \
  --exclude='products/desktop/pnpm-lock.yaml' \
  --exclude='products/desktop/packages/agent/pnpm-lock.yaml' \
  "$PATCH"
```

`--exclude` matches after `--directory` is prepended, so the patterns carry the `products/desktop/` prefix.
`git am` keeps each commit's original author and message; the commits are created and signed by you, which satisfies the signed-commit ruleset while crediting the source author.
On conflict, resolve and `git am --continue`; `git am --abort` resets.
The 3-way merge only works because step 1 fetched the source PR's objects.

3. Re-derive the excluded paths when the PR touched them:

- `.github/**`: look the workflow up in MIGRATION.md's mapping table. If it is in the dropped table the change is moot. Otherwise re-apply the source change to the ported root `desktop-*.yml` by following the transform rules, and invoke /authoring-ci-workflows before editing.
- Lockfiles: the monorepo copies carry local override pins from the drift list, so source lockfile hunks silently undo security pins. Land the `package.json` change, then regenerate from `products/desktop/` with `pnpm install --lockfile-only`, minding the `minimumReleaseAge` notes in MIGRATION.md.

4. Treat conflicts in drift-listed files (local security patches, `pnpm-workspace.yaml` overrides) as intentional monorepo divergence: keep the monorepo side and re-apply the PR's intent on top of it.

5. Verify from `products/desktop/`: `pnpm install --frozen-lockfile`, `pnpm typecheck` and `pnpm --filter <pkg> test` for the packages the PR touches. The desktop CI suite runs on the monorepo PR itself.

## Open the monorepo PR

- Title: keep the source title when it fits the monorepo's conventional-commit format; otherwise fix it up (desktop scope).
- Body: use `.github/pull_request_template.md`. Carry the original description over, rewriting bare `#N` references as `PostHog/code#N` so they do not resolve to unrelated monorepo PRs. State "Ports PostHog/code#N" so the pair is linked.
- Preserve draft state and assign the original author.
- Do not close or comment on the source PR without the author's say-so. The clean sequence is: link the monorepo PR from the source PR, then close the source once the port merges.

## Report

End a sweep with one line per source PR: ported to `#X`, skipped (why) or flagged for a human (why).
Never silently drop a PR from the sweep.
