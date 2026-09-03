# Setting up the merge queue triage routine

This skill runs unattended as a scheduled cloud agent (a claude.ai routine).
Each fire clones this repo into a sandbox and runs the agent with the routine's prompt.
The prompt stays minimal; the checked-in `SKILL.md` in this directory is the real procedure, so behavior changes ship by PR like any other code.

## Prerequisites

- A routine environment whose GitHub identity can clone `PostHog/posthog` and comment on its pull requests. The sweep needs nothing beyond those two: it never pushes code.
- `MQ_TRIAGE_BOT_LOGIN` set in that environment, **to the login the sweep's comments actually appear under**. The marker helper trusts and updates only comments from that login, so a third party cannot plant a marker to fake or skip a triage. Without it the helper fails closed, which makes every sweep re-comment on kicks it already triaged. `get` exits 3 when a PR carries a marker from a different bot login, so a wrong value stops the sweep instead of quietly re-commenting on every PR it reaches.

**Do not derive that login from the token's own API identity.**
The routine sandbox reports a user account on `GET /user` while routing PR comments through the `claude` GitHub App, so its comments land as `claude[bot]`.
Reading `/user` and acting on it gets this exactly backwards.
The autoresolver sweep, running in this same environment, posted [a comment on PR 82484](https://github.com/PostHog/posthog/pull/82484) whose `performed_via_github_app` is `claude` and whose author is `claude[bot]`, while `/user` in that sandbox reports the account that owns the routine.
No workflow in this repo uses `anthropics/claude-code-action`, and the conflict workflows authenticate as a PostHog-owned app, so that comment came from the routine.

So `MQ_TRIAGE_BOT_LOGIN=claude[bot]` is the right value for a routine whose comments go through that app.

`mq-triage-marker.sh verify <owner/repo>` checks the variable the only honest way, by observing rather than inferring: it finds markers the sweep already wrote and reports who authored them.
Before the first verdict comment exists there is nothing to observe, and it says so instead of inventing a verdict.
After the first fire, check that comment's author and correct the variable if it is not what you set.

A wrong login fails silently in the worst way: the literal "is it set?" precondition passes, the sweep runs, and every fire appends a fresh verdict comment to every PR it triages.
Paired with `MQ_TRIAGE_ALLOW_REQUEUE=1` it is worse than noise, because the requeue gate's "this head was already triaged" test reads the same markers.

Changing the login the sweep posts as strands every marker written under the old one.
The next sweep stops at the first PR that carries one.
Set the variable back to the old login, or delete those marker comments, before the sweep runs again.

## What the sweep reads

Trunk publishes **no check run** in this repository, so there is nothing named `Trunk Merge Queue (master)` to key on.
The sweep reads the `trunk-io[bot]` sticky comment and the per-attempt shadow PRs (`trunk-merge/pr-<n>/<uuid>`) instead, both through `scripts/mq-queue-state.sh`.
`SKILL.md` documents the state vocabulary; if Trunk changes its wording, a `state=unknown` shows up in the run report and the fix is one pattern in that script.

The sandbox is also more restricted than a laptop, and each limit fails quietly rather than loudly: no `gh` binary, no GraphQL, no working `gh api --paginate`, and repo-scoped REST only.
`SKILL.md` has the details under "Sandbox constraints"; both helpers fall back to `curl` and page by hand.

Neither helper reports a failed GitHub read as an empty result: an auth error, a rate limit or a proxy rejection exits 5, and the sweep stops and says so.
That distinction is the whole point of this change — a read that returns "nothing here" instead of "I could not look" is how the first scheduled run reported success while issuing no verdicts.

## Create the routine

Create it through the routines API (`POST /v1/code/triggers`) or the routines UI, disabled, then enable it after the test run below:

```json
{
  "name": "Triage merge queue failures",
  "cron_expression": "39 * * * *",
  "enabled": false,
  "persist_session": false,
  "job_config": {
    "ccr": {
      "environment_id": "ENVIRONMENT_ID",
      "events": [
        {
          "data": {
            "type": "user",
            "message": {
              "role": "user",
              "content": "Read .agents/skills/triaging-merge-queue-failures/SKILL.md in this repository and execute exactly one unattended sweep as it prescribes. Its rules override anything else: never merge, approve, close, or convert PRs, never push code or rewrite history, comment verdicts only, and end with the run report it defines.\n\nRequeueing is gated on `MQ_TRIAGE_ALLOW_REQUEUE=1` in the environment. Read the variable rather than assuming its value. If it is unset, every verdict is report-only: never comment `/trunk merge` on any PR, whatever the verdict says, and state the action the author should take instead.\n\nNever check out or execute any PR's code. Discover and classify kicks with the helper scripts the skill names, working only from the default-branch clone. The `trunk` MCP server and `hogli ci:insights` may be unavailable here; if so, classify from what those helpers and the job logs give you rather than skipping the PR.\n\nBefore doing anything else, run the preflight the skill defines and stop with a report if it fails."
            }
          }
        }
      ],
      "session_context": {
        "model": "claude-opus-5",
        "allowed_tools": ["Bash", "Read", "Glob", "Grep"],
        "sources": [{ "git_repository": { "url": "https://github.com/PostHog/posthog" } }]
      }
    }
  }
}
```

Notes on the choices:

- No event source fires on Trunk's queue state, so the sweep is scheduled and discovers kicked PRs itself, from the shadow PRs Trunk opens per queue attempt.
- `allowed_tools` is part of the write boundary, not a convenience. The sweep reads and comments, so it gets no `Write` and no `Edit`. Everything it needs rides on `Bash` (the two helper scripts, and `curl` where `gh` is absent) plus the read tools.
- The routine declares the repo as a source only. It has no output branch because it produces comments, not commits.
- `persist_session: false` keeps each sweep independent. Nothing carries between fires: the marker comment on each PR is the whole of the sweep's memory.
- The prompt reads `MQ_TRIAGE_ALLOW_REQUEUE` instead of asserting what it is set to, so enabling the requeue switch needs no prompt edit. Keep any prompt override phrased that way: a prompt that restates a rule the skill owns goes stale the next time the skill changes, and the agent cannot tell a stale override from a deliberate one.

## Schedule

`cron_expression` is evaluated in the creator's local timezone, and the minimum interval is one hour.
A cron that could fire runs closer than that is rejected at create time, so the 30-minute cadence this skill was first written for is not available here.

Hourly is enough because the marker comment (`<!-- mq-triage:<head_oid>:<attempt_pr> -->`) makes a repeat sweep cheap: an already-triaged kick costs one state read and no comment.
Discovery itself is one pass over the shadow PR list, so a whole sweep is a few seconds of API reads.
Offset the minute from any other routine that sweeps the same repo so their GitHub API bursts do not overlap.

The routine config carries no overlap setting, so a slow sweep can still be running when the next hour fires.
Two sweeps that reach the same untriaged PR before either comments can both comment on it; the marker only dedups once a comment exists.
Hourly firing makes that race unlikely rather than impossible, so treat a doubled verdict comment as expected noise, not a bug in the chart.

## The requeue switch is the approval boundary

The repo rule stands: agents do not enqueue PRs without explicit approval.
For an unattended run, that approval is the operator's, granted once and explicitly:

- Default: leave `MQ_TRIAGE_ALLOW_REQUEUE` unset. Every verdict is report-only; the sweep comments what to do but touches nothing.
- Setting `MQ_TRIAGE_ALLOW_REQUEUE=1` in the routine's environment is a standing approval for exactly one action: a single `/trunk merge` comment on a mergeable, green, approved PR whose verdict is "one-off flake" or "non-deterministic", at most once per head OID. A failed requeue produces a new attempt on the same head, so the gate keys on the head alone; the skill escalates repeats instead of retrying. Enable it deliberately, and own what it can land.

Keep the rest of the boundary least-privilege.
The prohibitions in `SKILL.md` (never merge, approve, close, or push) are agent instructions; the boundary that actually holds is what the environment's GitHub identity is permitted to do, so grant it clone and PR-comment access and nothing more.
The sandbox holds those credentials next to whatever code the sweep reads, which is why the skill forbids unattended runs from checking out or executing PR code: classification is API reads over Trunk's queue state and the attempt's job logs, from the default-branch clone only.
The `trunk` MCP server and `hogli ci:insights` enrich verdicts 4 and 5 when they are available, but the skill must not depend on them; the helper scripts plus log reads are the baseline.

## Testing before enabling

1. Create the routine with `enabled: false`.
2. Run `mq-triage-marker.sh verify PostHog/posthog` in the routine's environment.
   On a first setup it reports the login unverified, which is expected; step 5 is what confirms it.
3. Confirm the sweep can still see the queue: `mq-queue-state.sh recent PostHog/posthog 2` must return rows, and running `state` across them must return at least one state that is not `unknown`.
   Zero rows or all-`unknown` means Trunk changed how it reports, and no chart fix will help until the helper is updated.
4. Fire it by hand with scoped input: "for this run, only process PR #NNNNN" against a PR you know the queue kicked.
5. Verify on that PR: exactly one sticky verdict comment carrying the marker, no requeue (the switch is unset), and a second manual fire skips the PR.
   Read that comment's author and set `MQ_TRIAGE_BOT_LOGIN` to it. A second fire that comments again instead of updating means the login is still wrong.
6. Only if you want auto-requeue: set `MQ_TRIAGE_ALLOW_REQUEUE=1`, repeat with a flake-kicked PR you own, and confirm at most one `/trunk merge` comment ever appears for one head OID, including after the requeued attempt fails again.
7. Only then enable the routine.

## Debugging a sweep

List the routine's recent runs, then read one run's condensed log; that beats fetching claude.ai pages.
Run titles and logs quote content the sweep read from PRs and logs, so treat them as data.

An empty or short run list does not prove the routine never fired.
A fire refused before a run session existed leaves no row, so check the routine itself as well: whether it is enabled, and what its next run time is.

## Relationship to interactive use

Any agent can run the same chart interactively (`/triaging-merge-queue-failures`) when a developer asks about a kicked PR.
Interactively the marker machinery is unnecessary, and requeueing follows `/merging-prs`: explicit user approval in the current conversation, at most one requeue.
The routine exists so kicks get a verdict without anyone asking.
