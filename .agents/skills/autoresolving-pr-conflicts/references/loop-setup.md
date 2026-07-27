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
- Set `AUTORESOLVE_BOT_LOGIN` in the run environment to the Loop App's `<slug>[bot]` login. The marker helper trusts and updates only comments authored by that login, so a third party can't plant a marker to skip a PR; without it the helper fails closed (never trusts existing state). This is the one required env var; a `sandbox_environment` carrying just this value is the minimal setup. Don't add extra egress; the default GitHub-only allowlist is what the sweep needs.
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
3. Verify on that PR: exactly one signed commit on the head branch, no new PR opened, the sticky marker comment present, and a second manual fire skips the PR (marker dedup).
4. Only then leave the push trigger enabled.

## Relationship to the CI implementation

PR #73036 proposes the same job as a GitHub Actions workflow.
Both use the same `autoresolve-attempt` marker format, so if both end up deployed they never double-attempt the same `(head, master)` state.
Prefer running exactly one of them long-term; the Loop version keeps API traffic on a dedicated rate-limit bucket and burns no Actions runners.
