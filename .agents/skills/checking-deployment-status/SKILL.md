---
name: checking-deployment-status
description: >
  Determines whether a PostHog branch, commit, or pull request has deployed to
  PostHog Cloud (the `dev`, `prod-us`, and `prod-eu` environments). Use when the
  user asks "has my PR deployed yet?", "is my branch live?", "did my change ship
  to prod?", "is <PR/commit> in prod-us/prod-eu?", "what's currently deployed?",
  or mentions deploy status, rollout, shipping to production, or following a
  merged change to Cloud. Resolves a PR or branch to its merge commit, then uses
  the GitHub Deployments API plus an ancestor check (not a naive SHA match,
  because deploys are batched) to report which environments already contain the
  change. Read-only — never triggers, reruns, or blocks a deploy.
---

# Checking PostHog deployment status

Answer "has X deployed yet?" for a PostHog branch, commit, or PR. Resolve the
input to a commit SHA, then check — per environment — whether the currently
deployed code already contains that commit. This is read-only inspection.

## How PostHog deploys (the mental model)

- When a PR merges to `master`, CI builds a container image and dispatches a
  `commit_state_update` to the **[PostHog/charts](https://github.com/PostHog/charts)**
  repo, which orchestrates the actual rollout. `posthog/posthog` never deploys
  directly — charts does.
- Each rollout is recorded as a **GitHub Deployment** on `PostHog/posthog`,
  keyed by the built commit SHA and an `environment`: `dev`, `prod-us`,
  `prod-eu`. (You may also see `Release SDK` — that's SDK releases, ignore it.)
- Deploys are **batched and gradual**: a single build bundles several merged
  commits, and it reaches `dev` first, then `prod-us` / `prod-eu`. US and EU
  roll out independently.

The batching is the key gotcha: **your merge commit usually never gets its own
deployment record.** It gets folded into a later build cut at a different SHA.
So checking `deployments?sha=<your-merge-commit>` gives false negatives. The
correct question is _"is my commit an ancestor of the SHA currently deployed to
this environment?"_ — answer it with the compare API.

## Workflow

### 1. Resolve the input to a commit SHA

- **PR number** → get the merge commit. If it isn't merged yet, stop: there is
  nothing to deploy.

  ```bash
  gh pr view <pr> --repo PostHog/posthog \
    --json state,mergedAt,mergeCommit \
    --jq '{state, mergedAt, mergeCommit: .mergeCommit.oid}'
  ```

- **Branch** → resolve to the commit that actually landed on `master`. If the
  branch is unmerged, the work cannot be deployed; say so and stop.
- **Commit SHA** → use it directly (full 40-char SHA preferred for the compare
  API).

### 2. Check each environment

For each of `dev`, `prod-us`, `prod-eu`, find the SHA currently deployed there
and compare it against the target commit:

```bash
gh api "repos/PostHog/posthog/deployments?environment=<env>&per_page=1" \
  --jq '.[0].sha'                       # SHA currently deployed to <env>

gh api "repos/PostHog/posthog/compare/<target_sha>...<deployed_sha>" \
  --jq '.status'                        # ahead | identical | behind | diverged
```

Interpret the compare `status` (base = your commit, head = deployed SHA):

| status      | meaning                                            | verdict             |
| ----------- | -------------------------------------------------- | ------------------- |
| `identical` | deployed SHA _is_ your commit                      | ✅ deployed         |
| `ahead`     | deployed SHA is ahead of your commit (contains it) | ✅ deployed         |
| `behind`    | deployed SHA is behind your commit                 | ⏳ not yet          |
| `diverged`  | deployed line doesn't contain your commit          | ⏳ not on this line |

### 3. Or just run the helper

[`scripts/check-deploy.sh`](scripts/check-deploy.sh) does all of the above for a
PR number or a commit SHA:

```bash
.agents/skills/checking-deployment-status/scripts/check-deploy.sh 66924
.agents/skills/checking-deployment-status/scripts/check-deploy.sh 3428ae2ba593...
```

## Reporting

Give a per-environment verdict, and when something isn't deployed, say _why_ in
terms the user can act on — e.g. "merged 13:27, but the latest `dev` build was
cut 8 commits before yours, so it'll land in the next rollout." Useful extras:

- The merge time vs. the latest deploy time per env (a deploy that fired _before_
  the merge obviously can't contain it).
- That rollout is gradual, so `dev` leads `prod-us`/`prod-eu` by a cycle.

Web equivalents the user can bookmark:

- All deployments: <https://github.com/PostHog/posthog/deployments>
- Rollout progress: <https://github.com/PostHog/charts/actions>

To watch until it lands, re-run the helper (or the env loop) periodically — the
`/loop` skill can poll it and notify when prod flips to ✅.

## Boundaries

Read-only. Do **not** trigger, rerun, cancel, roll back, or block a deploy, and
do not push to charts — those are human-initiated actions. This skill only
reports state.
