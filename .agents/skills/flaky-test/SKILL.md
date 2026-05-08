---
name: flaky-test
description: >
  Triages a single failing test on a PostHog PR's CI run when it might be flaky
  or unrelated to the user's changes. Use when the user pastes a GitHub Actions
  run URL on their PR and asks to look at a failing test, invokes /flaky-test,
  or asks "is this CI failure mine?". Determines whether the failure is caused
  by the PR's diff (then stop and report), or unrelated (then open a draft fix
  PR off master and identify the owning team via CODEOWNERS so the user can
  ping them on Slack). Never posts to Slack itself — returns suggested reply
  text the user can paste.
---

# Triaging flaky / unrelated test failures on PostHog PRs

This skill is the *triage decision* layer on top of `debugging-ci-failures`.
For read-only inspection, classification, and local repro guidance, use the
`debugging-ci-failures` skill — this skill picks up after that, when the
question is: "is this failure mine, or someone else's?".

## When to invoke

The user gives a GitHub Actions run URL such as
`https://github.com/PostHog/posthog/actions/runs/<run-id>/job/<job-id>?pr=<pr>`
and asks you to look at the failing test. The PR number is in `?pr=`; the job
ID identifies the specific failing job within the workflow run.

## The contract

After inspecting the failure, every run produces *exactly one* of these:

1. **PR-caused** — tell the user the failure is theirs, with a one-sentence
   explanation. Stop. Do not open a fix PR. Do not tag a team.
2. **Unrelated, fixable** — open a draft fix PR off `master` (NOT off the
   user's branch). Identify the owning team. Return suggested Slack reply
   text linking the fix PR and tagging the team.
3. **Unrelated, not fixable in one PR** — don't open a PR. Identify the
   owning team. Return suggested Slack reply text summarizing the failure
   and tagging the team for triage.

Always *return* suggested Slack reply text — never post to Slack yourself.

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
exit without further action.

### Step 3 (unrelated only): Try to fix

Read the failing test and surrounding code to understand the root cause.
Common patterns:

- *Race / timing*: missing `await`, fixture ordering, time-based assertion,
  test depending on a shared resource without isolation.
- *State leakage*: a sibling test left state that this one depends on not
  existing, or vice versa. Look for class-level or module-level fixtures
  that aren't reset per-test.
- *Snapshot drift*: visual or string snapshot that needs regenerating after
  a legitimate change on master that the failing test forgot to keep up
  with.
- *Infra / runner*: no local repro is possible; treat per
  `debugging-ci-failures` and skip to the "not fixable in one PR" branch.

If the cause is clear and small, write the fix on a **new branch off
`master`** (not off the user's PR branch — the fix is independent and
shouldn't depend on the user's diff). Commit, push, and open as draft per
repo conventions:

```bash
git fetch origin master
git checkout -B posthog-code/fix-flaky-<short-name> origin/master
# ... make the fix ...
git push -u origin HEAD
gh pr create --draft --base master --title "fix(<scope>): ..." --body "..."
```

Use the `posthog-code/` branch prefix and follow conventional commits per
[CLAUDE.md](../../../CLAUDE.md). Keep the fix minimal — don't bundle
drive-by cleanups.

If the fix needs more than one PR (cross-cutting refactor, deeper
investigation, ambiguous root cause), don't open a PR. Capture what you
learned for the team handoff in step 4.

### Step 4: Identify the owning team

Look up CODEOWNERS for the failing test's path:

```bash
grep -E '<test-path-fragment-or-parent-dir>' .github/CODEOWNERS
```

CODEOWNERS uses longest-prefix match — start specific (the test file's
exact path) and walk up parent directories until you find a match. Cross-
reference with the public feature ownership handbook at
<https://posthog.com/handbook/engineering/feature-ownership> when CODEOWNERS
doesn't cover the path or the match is ambiguous.

Note that PostHog's CODEOWNERS file is intentionally sparse — most paths
have no explicit owner. When that's the case, the handbook's feature
ownership table is the source of truth. If neither resolves the owner with
confidence, say so explicitly in the suggested reply rather than guessing —
it's better to leave a question for humans than to ping the wrong team.

### Step 5: Compose the Slack reply

Return suggested reply text for the user to paste into Slack. Don't post
it yourself. Templates:

**Unrelated, fix PR opened:**

> Failure on `<test-path>::<test-name>` looks unrelated to your PR — the
> test exercises `<area>` which your diff doesn't touch. I opened
> <https://github.com/PostHog/posthog/pull/><n> with a likely fix. cc
> @PostHog/<team> — please review.

**Unrelated, not a one-PR fix:**

> Failure on `<test-path>::<test-name>` looks unrelated to your PR but
> isn't a one-PR fix — root cause appears to be `<short summary>`. cc
> @PostHog/<team> — flagging for triage.

**Unrelated, owning team unclear:**

> Failure on `<test-path>::<test-name>` looks unrelated to your PR. I
> couldn't confidently identify an owning team from CODEOWNERS or the
> feature ownership handbook — would appreciate a pointer.

## Safety rules

Inherit all safety rules from `debugging-ci-failures`. In addition:

- Never push to or modify the user's PR branch. Fixes go on a brand-new
  branch off `master`.
- Always open fix PRs as **draft**.
- Keep fix PRs minimal and scoped to the failing test's root cause. No
  drive-by cleanups, no scope creep.
- Never post to Slack — return suggested reply text only.
- Do not rerun CI, accept snapshots, or modify `.github/workflows/`
  without explicit approval.
- If you can't confidently determine PR-caused vs unrelated, say so and
  ask for human input — don't guess and open a PR you're unsure about.

## Reporting shape

Always respond with:

1. The failing test (path + name) and classification from
   `debugging-ci-failures`.
2. PR-caused decision with a one-sentence reason.
3. If unrelated:
   - link to the fix PR (if you opened one), or the reason no PR is
     possible
   - the owning team handle (or "unknown" if you couldn't determine)
   - the suggested Slack reply text, ready to copy-paste
