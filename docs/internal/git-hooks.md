# Git hooks

The repository uses Husky to install Git hooks when you run `pnpm install`.
The `pre-commit` hook runs checks on staged files.
The `pre-push` hook checks the merge queue before it runs `hogli ci:preflight --strict`.

## Merge queue check

The push check uses `gh` and `trunk` to check the pull requests for each branch in the push.
Run `trunk login` once to enable the queue check.
If a pull request is in the Trunk merge queue, the hook blocks the push.
Remove the pull request from the queue with `trunk merge cancel <number>`, wait for it to leave the queue, then push again.
A pull request with a failed batch, including the `Pending Failure` state, does not block a push with a fix.

The full queue check has a five-second timeout, shared by all branches and retries in the push.
The timeout stops the queue check and its child processes, then allows the push to continue to the other checks.
Missing `python3`, `gh`, or `trunk`, login errors, network errors, and unknown queue states also allow the push to continue.
The timeout does not apply to `hogli ci:preflight --strict`.
