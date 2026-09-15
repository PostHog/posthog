# Automatic review handover for task PRs

Task PRs still open as drafts. The snapshot-based PR monitor can make a draft ready after the agent finishes a successful turn and addresses CI failures and review comments. This requests review through the repository's existing review rules. It never approves or merges a PR.

## Enable the first release

Enable `tasks-pr-auto-ready` for selected users or organizations in PostHog. The flag is off by default and is checked before each attempt. The task must also use the PR loop and `tasks-pr-babysit-snapshot`. Its GitHub integration needs permission to write pull requests. The older task-management monitor and local runs do not use this transition.

To keep a PR in draft, add the `keep-draft` label. Create this label in each repository before enabling the flag. The `no-ci` label also prevents the transition. A task run with `state.keep_draft: true` stays in draft. A PR that someone has already made ready or returned to draft is left alone. Existing explicit preferences to open a report PR ready remain independent and can make it ready earlier.

## Transition rules

- The latest agent turn must end with `end_turn`. A timeout, cancellation, error, or missing completion result is not success.
- The agent must be inactive, with no queued follow-up message.
- All reported draft checks must pass. Missing, pending, failed, or unknown checks prevent the transition.
- GitHub must confirm that the PR has no merge conflict. No unresolved review thread or changes-requested review can remain.
- The monitor must have delivered all new review feedback. It does not treat delivery alone as resolution of a review thread.
- The activity reads the PR again. Its state, commit, and feedback must match the monitor's snapshot, and its repository must match the task run. The branch must match the stored task branch. If no task branch was stored, it must match the branch in the monitor's snapshot.
- The existing GitHub helper checks the commit, labels, and draft history again before the ready mutation. Repeated attempts do not repeat a completed transition.

GitHub does not provide an atomic ready mutation conditional on a commit. A change can arrive between the final read and mutation. Required checks and human approval still apply to the final commit.

Checks that start only after the ready transition do not block that transition. The existing monitor continues to handle those checks and new review feedback, within its normal time and iteration limits.

## Observe and stop

The task shows `PR ready for review` after a successful transition. Structured logs record `task_pr_auto_ready_evaluated`, `task_pr_auto_ready_skipped`, `task_pr_auto_ready_rejected`, and `task_pr_auto_ready_failed`. A GitHub or flag-service failure does not stop CI monitoring. A transport failure can occur after GitHub accepts the mutation; the next attempt reads the draft history instead of repeating the mutation.

For the first team, check completed runs left in draft, time from successful iteration to a review request, failures, and PRs people return to draft. Disable `tasks-pr-auto-ready` to stop further automatic transitions. Do not change existing ready PRs during rollback.
