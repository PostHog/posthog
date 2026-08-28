# Setting up the autoresolver Loop

This skill is executed by a [Loop](../../../../products/tasks/backend/models.py) (products/tasks): a cloud agent automation fired by GitHub events, where each fire spawns a task that clones this repo into a sandbox and runs the agent.
The Loop's `instructions` stay minimal; the checked-in `SKILL.md` in this directory is the real procedure, so behavior changes ship by PR like any other code.

## Prerequisites

- Tasks + Loops access on the team creating the loop (`loops` feature flag, `HasLoopsAccess`).
- A GitHub integration for the PostHog org whose App installation covers `PostHog/posthog` with `Contents: Read & Write` and `Pull requests: Read & Write`. Note its integration id.
- Strongly recommended: the VM sandbox runtime (`tasks-modal-vm-sandbox` flag) for the loop owner's origin, so the sandbox can run Docker — required for the credentialless regeneration defined in SKILL.md. Without it the loop still resolves source conflicts, but every generated-artifact conflict (lockfiles included) is flagged for a human.

## Create the loop

`POST /api/projects/:project_id/loops/` (session, personal API key, or OAuth):

```json
{
    "name": "Autoresolve PR conflicts",
    "description": "Sweeps open PRs that conflict with master after each push to master; resolves trivial conflicts, flags the rest.",
    "visibility": "team",
    "runtime_adapter": "claude",
    "overlap_policy": "skip",
    "instructions": "Read .agents/skills/autoresolving-pr-conflicts/SKILL.md in this repository and execute exactly one sweep as it prescribes. Its rules override anything else: write only to existing PR head branches it allows, never open or merge PRs, and end with the run report it defines.",
    "repositories": [
        { "github_integration_id": GITHUB_INTEGRATION_ID, "full_name": "PostHog/posthog" }
    ],
    "behaviors": { "create_prs": true, "watch_ci": false, "fix_review_comments": false },
    "triggers": [
        {
            "type": "github",
            "config": {
                "github_integration_id": GITHUB_INTEGRATION_ID,
                "repository": "PostHog/posthog",
                "events": ["push"],
                "filters": { "branches": ["master"] }
            }
        }
    ]
}
```

Notes on the choices:

- `overlap_policy: "skip"` is the debounce: pushes to master that land while a sweep is running are dropped, and the running sweep already picks up the newest master state per PR.
- `behaviors.create_prs: true` is the write-mode switch ("whether the agent may push branches and open PRs"). The skill's rules then forbid opening PRs; write access is needed solely to push to existing PR heads. `watch_ci` and `fix_review_comments` stay off: this loop creates no PRs of its own to follow up on.
- The push trigger only fires for pushes by users with write access (the loop pipeline's trusted-actor gate), and pushes to `loop/*` branches are excluded from triggering, so the loop cannot fire itself.

## The write boundary is enforcement, not prose

The skill's prohibitions (no PR creation, no history rewrites, no protected-branch writes) are agent instructions; the boundary that actually holds is what the runtime enforces.
Keep that boundary least-privilege:

- The GitHub App installation behind the integration should grant only `Contents: Read & Write` and `Pull requests: Read & Write`, on as few repos as possible. Never widen it for this loop.
- Leave `connectors.posthog_mcp_scopes` at its `read_only` default and attach no MCP Store installations; the sweep needs neither.
- Set `AUTORESOLVE_BOT_LOGIN` in the run environment to the login that authors the sweep's comments. The marker helper trusts and updates only comments authored by that login, so a third party can't plant a marker to skip a PR; without it the helper fails closed (never trusts existing state), and `get` exits 3 when a marker exists under another login, so a wrong value fails loudly instead of silently re-resolving every PR. This is the one required env var; a `sandbox_environment` carrying just this value is the minimal setup. Don't add extra egress; the default GitHub-only allowlist is what the sweep needs.
- The sandbox's git guard (signed commits only, no raw `git push`) and GitHub's protected-branch rules are load-bearing; treat any run that reports friction with them as a bug in the run, not a reason to loosen them.
- Regeneration isolation and untrusted-input handling are defined once, in SKILL.md and its `scripts/`; don't restate or weaken them here. If the tasks platform ships first-class nested credentialless sandboxes, adopt them.
- If the tasks platform ships an enforced "push to existing branches, never create PRs" behavior flag, adopt it here and drop the reliance on `create_prs: true` plus instructions.

## Operational limits to know

- Per-loop rate cap: 100 created fires/day; per-team: 500/day. With `overlap_policy: skip`, bursts of master merges collapse into far fewer fires, but on a very busy day the cap can still bite; conflicts left over simply wait for the next fire or a manual run.
- The loop auto-pauses after 5 consecutive failed fires; check the loop's `runs/` history if sweeps stop.
- The sandbox's GitHub token comes from the App installation, so all API traffic (PR listing, comments) draws on the App's own rate-limit bucket, not the shared per-repo `GITHUB_TOKEN` pool that CI workflows compete over.
- Fires are deduped on the webhook delivery GUID, so redeliveries never double-spawn a sweep.

## Testing before enabling for real

1. Dry-run the config: `POST /api/projects/:project_id/loops/:id/preview/`.
2. Manual fire: `POST /api/projects/:project_id/loops/:id/run/` with instructions appended via the run input to scope the sweep, e.g. "for this run, only process PR #NNNNN" against a disposable conflicting PR you opened yourself.
3. Verify on that PR: exactly one new commit on the head branch and it has two parents, the PR's changed-file count still reflects only its own changes, no new PR opened, the sticky marker comment present, and a second manual fire skips the PR (marker dedup).
4. Only then leave the push trigger enabled.

## Relationship to the CI implementation

`.github/workflows/pr-autoresolve-conflicts.yml` runs the same job as a GitHub Actions workflow.
Its schedule is disabled and it stays dispatchable by hand, so it is a fallback rather than a second scheduled sweep.

Both write the same `autoresolve-attempt` marker format, so if both do end up running they never double-attempt the same `(head, master)` state.
Keep exactly one of them scheduled; the Loop version keeps API traffic on a dedicated rate-limit bucket and burns no Actions runners.

That workflow cannot land a resolution today, and `commit-resolved.mjs` now says so on the PR instead of failing silently.
It used to gate the commit on `branches/<ref>.protected`, which matches every branch because an org-level ruleset targets all of them, so it never committed and nobody saw the real blocker underneath.

The real blocker is that no mechanism available to it can record two parents:

- `createCommitOnBranch` is the only way to get GitHub to sign a commit without holding a signing key, and it creates one commit with one parent.
- `git/commits` does accept two parents, but produces an unsigned commit, and a `required_signatures` ruleset covers PR branches, so the ref update is rejected.
- The `finalize` job holds the write token and deliberately checks out only trusted scripts, so it has no merged tree to commit from.

Unblocking it means giving the App a signing key, after which `finalize` can fetch both refs, merge, and push a real merge commit.
Until then the CI path marks conflicting PRs for a human, and the Loop path is the only one that resolves anything.
A sandbox that provides a commit signer can run `git merge` plus `git push` directly, which records both parents; where the sandbox blocks raw git and the signing tool takes only one parent, SKILL.md has the agent flag the PR rather than flatten the merge.
