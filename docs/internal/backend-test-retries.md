# Backend test retries

Backend CI retries each failed pytest test once, in the same pytest process, with a one-second delay.
The Django core and Temporal jobs and the Turbo product jobs use `--force-reruns 1 --reruns-delay 1`.
The Depot workflow uses the same budget.
This overrides per-test retry markers, including markers that request more retries.
Local test commands retain their existing retry settings.

Pytest keeps control of the result: a passing retry passes, and a second failure fails.
Collection errors and a killed test process are not rescued by this mechanism.
CI does not rerun the step or job automatically.

## Keeping the failure evidence

The existing JUnit hook records `posthog.reruns` on the final test report.
For retried tests it also records the executing GitHub `RUNNER_NAME` as `posthog.runner_name`.
The timing reporter exports these as `test.attempts`, `test.outcome` (`rerun_passed` for a recovered test), and `test.runner_name`.
Recovered tests are retained even if they are below the normal duration threshold.
Engineering analytics already treats `rerun_passed` as evidence of flakiness.

CI enables `-rR` and the JUnit plugin prints failed-attempt tracebacks in the terminal summary.
The pinned pytest-rerunfailures 16.1 otherwise prints only rerun node IDs.
The job-log collector includes successful jobs with a matching recovered-test span, using the repository, workflow run, run attempt, and runner name.
If a runner is reused for several jobs in one run attempt, those successful jobs can also be collected.
The normal log retention limits still apply, and `RERUN` lines preserve the surrounding diagnostics during thinning.
These logs retain the job's `success` conclusion; recovery is not a persistent job failure.

Trunk still receives the final JUnit result.
This preserves retry evidence in Engineering analytics, but does not restore Trunk's visibility into each failed attempt.
