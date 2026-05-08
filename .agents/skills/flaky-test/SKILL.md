---
name: flaky-test
description: >
  Triages a single failing test on a PostHog PR's CI run when it might be flaky
  or unrelated to the user's changes. Use when the user pastes a GitHub Actions
  run URL on their PR and asks to look at a failing test, invokes /flaky-test,
  or asks "is this CI failure mine?". Decides whether the failure is caused by
  the PR's diff (then say so and stop) or unrelated (then identify the owning
  team via CODEOWNERS / the feature ownership handbook, resolve the Slack
  sub-team mention by listing user groups via the Slack MCP — never hardcoded,
  never guessed — and reply with that mention inline so the team is actually
  pinged). Never opens a fix PR; opening one requires explicit follow-up
  authorization from the user.
---

# Triaging flaky / unrelated test failures on PostHog PRs

This skill is the _triage decision_ layer on top of `debugging-ci-failures`.
For read-only inspection, classification, and local repro guidance, use the
`debugging-ci-failures` skill — this skill picks up after that, when the
question is: "is this failure mine, or someone else's?".

## When to invoke

The user gives a GitHub Actions run URL such as
`https://github.com/PostHog/posthog/actions/runs/<run-id>/job/<job-id>?pr=<pr>`
and asks you to look at the failing test. The PR number is in `?pr=`; the job
ID identifies the specific failing job within the workflow run.

## The contract

After inspecting the failure, every run produces _exactly one_ of these:

1. **PR-caused** — tell the user the failure is theirs, with a one-sentence
   explanation. Stop. Do not tag a team.
2. **Unrelated** — identify the owning team and reply with the resolved
   Slack sub-team mention inline so the team is actually pinged.

The reply is the bot's response in the calling channel — write it as the
final message, with the real `<!subteam^...>` mention rendered inline. Do
not return placeholder text the user has to copy, paste, or tag manually;
that defeats the point of the skill.

Never open a fix PR — opening one requires explicit follow-up authorization
from the user, even when the cause is obvious. Stop after the reply and let
the user decide.

## Workflow

### Step 1: Inspect

Use the read-only inspection commands from `debugging-ci-failures`:

```bash
gh pr view <pr> --json number,headRefName,baseRefName,files,statusCheckRollup
gh run view <run-id> --json jobs,conclusion,name,workflowName,url
gh run view <run-id> --log-failed
```

Extract:

- failing test path and test name (e.g. `posthog/api/test/test_foo.py::TestFoo::test_bar`)
- the workflow + job + step that failed
- the PR's changed file list
- the relevant diff context for the failing test's code path

### Step 2: Decide if PR-caused

Read the failing test source and compare to the PR's diff. The failure is
**caused by the PR** if any of these are true:

- the failing test file or files it imports are in the PR's `files` list
- the test exercises a code path the PR changed (transitive imports, shared
  utilities, modified models / serializers / HogQL nodes the test touches)
- the failure mode (assertion text, snapshot diff, error message) clearly
  maps to a behavior the PR introduced

Sanity check via `master`: look at the same job's recent history with
`gh run list --branch master --workflow <workflow> --limit 20`, and check
whether the test has been failing on `master` independently. A test that
passed on `master` at the PR's base SHA and only fails on this PR is more
likely PR-caused — but pre-existing flakes can also surface on a single PR
purely by chance, so weigh this signal against the diff analysis above.

If PR-caused → STOP. Tell the user, point to the suspect commit / file, and
exit without further action. Do not tag a team — pinging a team for a
PR-caused failure is noise.

### Step 3: Resolve the owning team — twice

You need _two_ identifiers and they are not interchangeable:

- a **GitHub team handle** like `@PostHog/team-product-analytics`, used
  internally to resolve ownership
- a **Slack handle** for the corresponding user group, used in the Slack
  reply

A GitHub team handle pasted into Slack does not ping anyone. Always resolve
the Slack handle separately. Do **not** hardcode a github-team-to-slack
mapping inside this skill or guess based on naming similarity.

#### 3a. GitHub team via CODEOWNERS / handbook

Look up CODEOWNERS for the failing test's path:

```bash
grep -E '<test-path-fragment-or-parent-dir>' .github/CODEOWNERS
```

CODEOWNERS uses longest-prefix match — start specific (the test file's
exact path) and walk up parent directories until you find a match. PostHog's
CODEOWNERS is intentionally sparse — most paths have no explicit owner.
When that's the case, the public feature ownership handbook at
<https://posthog.com/handbook/engineering/feature-ownership> is the source
of truth (`WebFetch` it, search for the directory or feature name).

The output of this step is a _team identity_ — the GitHub handle if
CODEOWNERS gave one, otherwise the team's name as written in the handbook
(e.g. "Product analytics", "Replay", "Pipeline"). That identity is the
input to step 3b.

#### 3b. Slack handle via the Slack MCP

The harness should expose a Slack MCP server with user-group / sub-team
listing tools (typical names: `slack_get_user_groups`,
`slack_user_groups_list`, `list_user_groups`, `usergroups.list`). List
all user groups, then match the team identity from 3a against:

- the user group's `handle` (e.g. `team-replay`)
- the user group's `name` / display name
- the user group's `description`

Pick the user group whose handle/name most directly corresponds to the
GitHub team or feature-handbook entry. If the GitHub handle is
`@PostHog/team-replay` and Slack has a user group with handle
`team-replay` or name `Team Replay`, that's the match. If the only match
candidates differ (e.g. handbook says "Pipeline" and Slack has both
`team-pipeline` and `team-pipeline-ingest`), prefer the more general one
unless the failing test path narrows it.

For the actual ping, use Slack's sub-team mention syntax so the message
pings the group:

```text
<!subteam^SXXXXXXX|team-replay>
```

`SXXXXXXX` is the user group's `id` from the list call; `team-replay` is
its `handle`. A bare `@team-replay` in skill output text does not ping —
only the `<!subteam^...>` form does.

If no Slack MCP is available, or no user group plausibly matches, do not
guess a handle — fall through to the "Slack handle unresolved" reply
template below and ask the user to fill in the right handle.

### Step 4: Reply

This is the bot's final response. Write it directly — render the actual
`<!subteam^...>` mention inline so the team is pinged the moment the
message lands. Do not output a placeholder like `<slack-team-mention>` and
do not ask the user to paste, edit, or tag manually; that defeats the
purpose of resolving the mention.

Substitute the values you resolved in steps 1–3 inline:

**Unrelated, owning team resolved:**

> Failure on `<test-path>::<test-name>` looks unrelated to your PR — the
> test exercises `<area>` which your diff doesn't touch. Suspected cause:
> `<short summary>`. cc <!subteam^SXXXXXXX|team-handle> — flagging for
> triage.

**Unrelated, Slack handle unresolved** (only when step 3b genuinely
couldn't match a user group — never as a shortcut to skip the lookup):

> Failure on `<test-path>::<test-name>` looks unrelated to your PR.
> Suspected cause: `<short summary>`. I believe the owning team is
> `<team identity from 3a>` (per CODEOWNERS / feature-ownership handbook),
> but I couldn't resolve the Slack handle — could you tag them?

If the user later asks you to attempt a fix, defer to whichever skill or
workflow they invoke for that next step — opening a fix PR is out of scope
for this skill.

## Safety rules

Inherit all safety rules from `debugging-ci-failures`. In addition:

- Never open a fix PR. Even when the root cause is obvious and the fix is
  one line, opening a PR requires explicit follow-up authorization from
  the user. Describe what the fix would look like in the suggested Slack
  reply if helpful, but stop short of making it.
- Never push to, modify, or otherwise touch the user's PR branch.
- Never hardcode or guess a Slack handle. The team-to-Slack mapping must
  always be resolved at run time via the Slack MCP. If no Slack MCP is
  available or no user group plausibly matches, use the "Slack handle
  unresolved" template and let the user fill it in. Don't use that
  fallback as a shortcut to skip the lookup.
- The reply you produce is the bot's actual response in the calling
  channel — render the resolved `<!subteam^...>` mention inline rather
  than asking the user to paste or tag manually.
- Do not rerun CI, accept snapshots, or modify `.github/workflows/`
  without explicit approval.
- If you can't confidently determine PR-caused vs unrelated, say so and
  ask for human input — don't guess.

## Internal analysis (not the response)

Before composing the reply, internally work through:

1. The failing test (path + name) and classification from
   `debugging-ci-failures`.
2. PR-caused decision with a one-sentence reason.
3. If unrelated:
   - the suspected root cause (one short sentence)
   - the GitHub team handle / feature-handbook team name (or "unknown")
   - the resolved Slack sub-team mention as `<!subteam^...>` (or
     "unresolved" — never guessed)

Do not output these as the response. The final user-facing message is the
reply defined in Step 4, written as a single conversational message with
the resolved mention rendered inline.
