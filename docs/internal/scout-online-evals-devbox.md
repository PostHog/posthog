# Online scout trials in a devbox

Trials compare versions of a scout against its saved rubric. Each version can change the prompt, model or reasoning effort, with repeated runs to check consistency.
Scouts run in parallel through the real application, tools, sandboxes and model gateway. The server judges their saved evidence and produces a comparison report.
Use a devbox with synthetic data for validation. Scout execution, rubric generation and judging incur model charges.

## Prerequisites

Use the existing [devbox setup](../../.agents/skills/setting-up-devbox/SKILL.md) and [local stack](../../.agents/skills/run-posthog/SKILL.md) instructions.
Preserve the devbox's synthetic dataset. Keep credentials, prompts, transcripts and downloaded reports outside version control.

- The Trials UI and scoring require a staff user in project 2, with project membership and permission to edit the source skill.
- The source scout must support reports through `emit_report` or `edit_report`. Trials reject extra product write scopes, external MCP servers and structured-output schemas.
- Backend, frontend, MCP, Temporal, Docker sandboxes, databases, Redis and object storage must be ready. The normal Temporal worker runs both scouts and judging.
- Trials use the [Go AI gateway](https://github.com/PostHog/ai-gateway) with private scoped tokens. They do not fall back to the Python gateway or subscription credentials.
- Provider credentials must support the scout models returned by trial setup and the judge model, currently `gpt-6-astra`.

Use the normal local OAuth setup, including `setup_tasks_oauth`, and register Temporal search attributes if the devbox has not already done so.
The gateway's mint credential must belong to the intended paying project. Keep the Temporal worker on the same code revision as the backend.
Disable worker hot reload during paid runs with `TEMPORAL_DISABLE_HOT_RELOAD=1`.

### Routing and capture

Sandboxes need direct service URLs that do not pass through the browser's Coder login proxy.
For services on the devbox host, the usual settings are below; verify the actual ports and Docker host mapping:

```dotenv
SANDBOX_PROVIDER=docker
SANDBOX_API_URL=http://host.docker.internal:8000
SANDBOX_MCP_URL=http://host.docker.internal:8787/mcp
SANDBOX_AI_GATEWAY_URL=http://host.docker.internal:8080
AI_GATEWAY_URL=http://localhost:8080/v1
```

MCP also needs a direct `POSTHOG_API_BASE_URL` for backend calls. Keep `POSTHOG_PUBLIC_URL` and the application's `SITE_URL` on the public browser URL.

Configure `SANDBOX_AI_GATEWAY_MINT_KEY` through private local settings. Use a server credential authorized for team attribution; trial tokens pin the `signals_scout` product and must not bill customer credits.
Trials route to Go independently of the ordinary scout rollout allowlist.

Deploy support for scoped tokens with `capture_mode: none` to every gateway replica before enabling trials. Then set both flags on the backend and worker:

```dotenv
SCOUT_LIVE_TRIALS_ENABLED=true
SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=true
```

`SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE` confirms that query/task telemetry and warehouse replicas do not expose trial content to the project being inspected.
The caller also requires the gateway to acknowledge capture suppression when minting each token. An older gateway's token is revoked and rejected.
The gateway suppresses trial generation, exception and rate-limit denial events, while retaining usage accounting and spend/rate limits. Ordinary requests keep their normal capture behavior.
Revoke or expire private tokens before rolling the gateway back to a version without this support.
For local validation, direct telemetry to a separate destination. Globally disabling capture does not prove trial-specific suppression.

Set a test budget before launching runs. The existing `SANDBOX_AI_GATEWAY_TOKEN_CAP_USD` and product cap settings bound each scoped token's spend.
The gateway needs its normal persistent Redis and ledger configuration. An unavailable cost is not zero cost.

## Run a trial

1. Open a supported scout over the synthetic data. In its rubric editor, generate suggestions, review the checks and captured reference instructions, then save the checklist. Unsaved defaults or suggestions cannot be scored.
2. Open **Trials → New trial**, or select the scout at `/project/2/scout-trials`. Check any setup blocker before launching.
3. Start with two versions and one run per version. Change the second version's model, effort or prompt. **Current** uses the saved scout prompt; **Custom** replaces it only for that version.
4. Select **Start trial**. The server saves the versions, rubric and starting history, runs the scouts, then judges automatically. Closing the page does not stop the trial.
5. Read the result, compare checks across versions, and open individual runs for reports and criterion evidence. Reopen the saved trial or export its JSON report without another model call.

A trial supports 2–20 versions and 1–20 runs per version, up to 400 runs. There is no overall concurrency cap across trials; each trial judges three runs at a time.
Start small: repeats increase scout and judge costs. Available models, effort choices, permissions and launch blockers come from `trial_setup/`.

## Judging and results

The saved rubric stays fixed across scout edits. Trials never regenerate it automatically.
Only an explicit saved rubric update changes future grading. Each trial freezes its checklist and reference instructions before scouts start, so all versions use the same requirements.
Editing the rubric during a trial does not change that trial. Incomplete captured references must be regenerated, reviewed and saved before scoring.

The judge reads bounded evidence from reports, memory changes, summaries and available tool calls/results.
It receives the fixed requirements without version labels or scout model settings. Candidate prompts and launch notes cannot relax the rubric or prove that an action happened.
Each check returns **pass**, **fail**, **unknown**, or **not applicable**, with reasons and supporting evidence. Invalid citations fail judging; missing proof remains unknown.
Missing or truncated evidence is visible in the report. The judge does not independently query source truth or measure missed findings.

The winner passes the most checks across repeated runs, with equal weight for each check. Cost and speed are shown separately.
A winner requires at least two versions, equal repeat counts and complete judgments on the same applicable checks. Equal top totals produce a tie.
Unknown verdicts, failed or missing runs, judge errors, or different applicability produce **No clear winner**.
An execution failure remains excluded even if it left partial output. A report containing only judge errors is not a successful comparison.

For exported metrics, a run's score is `pass / (pass + fail)`, or null without decisive verdicts; a version's score is the equal mean of its non-null run scores.
Coverage is `(pass + fail) / (pass + fail + unknown)`. Not-applicable checks are excluded from both denominators.
These scores describe the captured runs; they do not establish statistical significance or guarantee results on other data.

Saved evaluations retain their original rubric, evidence, judge model and judging rules. Reading an older report does not rejudge it.
Exact-ID retries reuse the original request. New evaluations require a reviewed saved rubric, even when an older report used a mock checklist.

## Isolation and recovery

Versions share starting history but keep separate writable memory and captured reports. They do not change the source scout's instructions, shared memory or normal inbox.
Trial tasks, logs, artifacts and results are accessible only to the launching operator or the sandbox bound to that task. Other project members cannot discover them through ordinary task lists or searches.
Shared starting history does not freeze live project data or the clock; keep synthetic inputs stable during a comparison.

Trial reports cannot create or cancel follow-up checks, record their results, or persist typed report links. Unsupported operations return explicit errors; they must not be treated as successful execution.
Existing live report checks remain readable. Skill reads serve the pinned candidate; stub skill bundles are supported, while full-content bundles and ZIP exports are unavailable to trial credentials.

Polling and reloading only read saved state. Resume the same saved trial after an interruption instead of creating fresh launch IDs.
Retries do not automatically repeat an attempted paid judge call. A deliberate **New scoring attempt** can reuse completed scouts with the current saved rubric, creates a new evaluation ID, and may charge for judging every run again.
It preserves the previous report. A timeout does not cancel server runs; inspect their state and use the task controls to stop an active run.

## API and CLI

The scout API base path is `/api/projects/{team_id}/signals/scout/configs/{config_id}/`:

| Endpoint                                                        | Purpose                                                                   |
| --------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `GET trial_setup/`                                              | Supported settings and launch blockers.                                   |
| `POST trial_comparison/`                                        | Start a saved trial with automatic judging.                               |
| `GET trial_comparison_result/`, `GET trial_comparison_history/` | Read a trial or list saved trials.                                        |
| `POST trial_comparison_resume/`                                 | Resume the same saved work.                                               |
| `GET trial_result/`                                             | Read one launch's execution result.                                       |
| `POST trial_evaluation/`, `GET trial_evaluation_result/`        | Start a deliberate scoring attempt for existing runs, or read its result. |

Separate scoring uses `rubric_source: saved`. Runs must share the scout, operator and starting context; settings must match within each version.
Reuse an evaluation ID only with its exact saved request. Polling reads the saved status without starting a judge.

The [operator CLI](../../products/signals/eval/run_live_trials.py) launches, resumes and downloads individual runs; it does not score them. Use the UI or comparison API for the complete flow.
Run `.codex/with-flox python products/signals/eval/run_live_trials.py --help` from the repository root for its options.
It reads `POSTHOG_API_KEY` and requires `signal_scout:write`, `llm_skill:write` and `task:read` scopes. Load the key through private local configuration.
Keep the output directory private and outside Git. Resume with the same host and output directory plus `--resume`; the manifest preserves launch IDs, context and concurrency.
Only one CLI controller may use an output directory at a time.

## Troubleshooting and validation

| Symptom                               | Check                                                                                                                                     |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Setup/scoring returns 404             | Staff status, project 2, project membership and source skill access.                                                                      |
| Setup is blocked                      | `blocked_reason`, both trial flags, source capabilities, fleet enrollment and quotas.                                                     |
| Run stays queued                      | Temporal worker revision, local OAuth setup, task queue and Docker sandbox readiness.                                                     |
| Sandbox receives HTML or a login page | Direct sandbox URLs and MCP's backend URL; avoid the browser proxy.                                                                       |
| Gateway returns 401/403               | Go mint credential, private capture acknowledgement, token expiry and provider authorization. Readiness alone does not test model access. |
| Result export or scoring fails        | Object storage readiness, worker logs and the saved error. Preserve IDs before retrying.                                                  |
| Most checks are unknown               | Missing or truncated tool evidence; do not turn missing proof into a pass.                                                                |

Validate one complete real trial before increasing its size. Reopen and export the report, confirm no extra paid calls, and check that another local user and sibling sandbox cannot read its private state.
Check private capture with an ordinary request and a trial request: ordinary telemetry should remain, trial content should be suppressed, and both should retain spend/rate limits.
For judge accuracy, use synthetic cases with known answers, including a clear issue, a quiet period and incomplete evidence. Label expected outcomes before reading judge verdicts; record missed findings and false positives separately.
