# Read and compare eval results

Use this reference after a run, before accepting a change to a prompt, tool, skill, or model.

## Find the evidence

The final summary contains scorer averages, result URLs, and an `Agent logs` directory for each experiment.
Use those URLs when results upload to PostHog or Braintrust.
Private runs keep local results by default.

Every real invocation writes a full stdout and stderr transcript under:

```text
products/posthog_ai/eval_harness/logs/harness/<timestamp>_<id>.log
```

The final terminal line gives its absolute path.
`logs/harness/latest.log` points to the newest transcript.
`--list` and argument errors do not create transcripts.
The transcript includes detailed logs even without `--verbose`.
`EXPORT_EVAL_RESULTS=1` also appends structured summaries to `eval_results.jsonl`.

In the interactive view, select a trial to inspect its status.
Select `Run` for setup information. Press `l` for the full transcript during execution.
Per-trial files become available after execution.
Use `--no-tui` for plain text output.
Press Ctrl-C once to cancel and let cleanup finish.

## Interpret status and scores separately

| Result                    | Meaning                                  | Effect on the run                                            |
| ------------------------- | ---------------------------------------- | ------------------------------------------------------------ |
| Score `1.0`               | The scorer's requirement passed          | Included in the mean                                         |
| Score `0.0`               | The scorer's requirement failed          | Included in the mean                                         |
| Score between 0 and 1     | Partial credit under that scorer's rules | Included in the mean                                         |
| Score `None`              | The scorer skipped the requirement       | Excluded from the mean                                       |
| Case infrastructure error | Setup or execution infrastructure failed | Excluded from score means; process exits nonzero             |
| Case timeout              | The agent exceeded the case budget       | A scored agent failure; use `--fail-under` to enforce a gate |
| Suite `CRASH`             | The suite failed to complete             | Process exits nonzero; other suites continue                 |

`CASE READY` means execution finished, but scores are still pending.
`CASE DONE`, `EXPERIMENT DONE`, and `SUITE DONE` mean the relevant work completed. They do not mean every requirement passed.
Only the overall run uses `PASS` or `FAIL`.

Without `--fail-under`, low behavioral scores alone do not make the command fail.
With `--fail-under`, the harness checks the mean across experiments.
A mean can hide a failed requirement, so inspect the relevant scorer and case results too.
Upload failures warn but do not change the score gate.
A completed result upload keeps its link even if the later tagging step fails.

## Compare a proposed change

Keep the suite, cases, seed data, runtime, model, reasoning effort, and skill delivery mode constant.
Change only the behavior that the comparison needs to measure.
Record the revision and command for both runs.

For example, run the same selected case on the base version and on the proposed version:

```bash
hogli evals sql/eval_sql::eval_sql \
    --eval sql_pageviews_by_browser \
    --trials 3 \
    --max-sandboxes 1 \
    --fail-under 0.8 \
    --no-tui
```

The threshold is an example. Choose a threshold that fits the suite's requirements.
Use `--agent-model` to pin the model for comparisons over time.
Use bare model IDs, without an `anthropic/` or `openai/` prefix.

The summary shows a 95% confidence interval for each scorer, clustered by case.
With repeated trials, it also shows:

- `pass^N`: the fraction of cases where every trial passed.
- `pass@N`: the fraction of cases where at least one trial passed.
- Flaky cases: cases with both passing and failing trials.

For these trial measures, a passing score is `1.0`. Partial credit does not count as a pass.
These measures include only cases with scores for all N trials.
The confidence interval needs at least two scored cases.
Check skipped and errored cases before comparing means.
Use failures in individual cases to explain a score change. Do not infer a reliable improvement from one successful trial.

## Diagnose a failure

1. Open the transcript from the final terminal line.
2. Find the failing case and its phase, exception, or timeout reason.
3. Open the experiment's `Agent logs` directory.
4. Read the trial summary and scorer metadata.
5. Read the raw agent log to check tool inputs, tool results, and the final answer.
6. Rerun that case after correcting the cause.

A low score can indicate an agent failure, a faulty scorer, or data that does not match the case.
Check all three before changing a prompt to satisfy the scorer.
A successful tool call alone does not prove that the answer is correct.

Temporary setup and service-readiness failures receive two retries by default.
`CASE RETRY` and `STARTUP RETRY` identify these retries.
`--infra-retries 0` disables them for diagnosis.
The harness does not retry low scores, agent work, case timeouts, authentication errors, or setup code errors.

The case budget starts after team setup.
Follow-up messages share the case deadline. They do not each receive a new full budget.
For a timeout, inspect the transcript even if the raw agent log is empty.
Use `--case-timeout` only when the task needs a different budget.
