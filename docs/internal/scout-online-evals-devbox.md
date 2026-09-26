# Online scout evaluation in a synthetic devbox

Use this document as the task handoff to an agent **inside an existing PostHog devbox**. Here, “online” means scouts use the real running application, tools, data queries, sandbox and model providers against the devbox's synthetic project. The scoring rubric is a mock; scout execution and judging should be real.

Start by reading this document and the repository's `AGENTS.md`. Follow the stages in order, fix local setup problems, and continue through a saved scored comparison and a first quality iteration. Preserve the existing synthetic dataset. Record any required local adaptations and the exact code revision used.

## Starting point and boundaries

- Implementation branch: `signals/scout-live-experiments`, [PR #105078](https://github.com/PostHog/posthog/pull/105078).
- Known implementation commit: `b56358a961ee70992b30840a7fddb38b4b7841ab`. Fetch the branch for this guide and later fixes; record the resulting SHA.
- Implemented: private repeated scout launches, shared starting history, prompt/model/effort variants, saved results, explicit paid scoring, criterion evidence, comparison reports and JSON export.
- Still needs a real end-to-end check: the current shared Python gateway's private route and the real comparison judge. Passing unit tests and mocked browser stories do not establish this.
- Rubric editing, generation and storage belong to [PR #106580](https://github.com/PostHog/posthog/pull/106580). Keep the replaceable mock for this exercise. Do not implement another editor or rubric store.
- This guide authorizes no production operation. Use only the devbox's synthetic project and local services. A remote model provider can still charge for inference.

Use the existing remaining test budget agreed with the operator. Record a cap and a running ledger before paid calls; missing usage or `cost: null` does not mean free. Begin with one small run. Stop repeated authentication, routing or provider failures before they consume the budget.

The gateway exempts staff users from per-user cost caps by default. Fleet limits and gateway limits do not enforce this exercise's dollar budget; use bounded batches and provider accounting.

For local spend checks, set `LLM_GATEWAY_STAFF_UNLIMITED_USAGE=false` and an explicit `LLM_GATEWAY_REDIS_URL` pointing to the devbox's existing Redis. The standalone gateway does not inherit Django's `REDIS_URL` fallback; without its own URL, it uses reduced in-memory limits and loses counters on restart. To inspect `/metrics`, also set `ENABLE_METRICS=true` alongside `LLM_GATEWAY_METRICS_ENABLED=true`. Confirm the running endpoint exposes the intended Signals cost limit before making paid calls.

## 1. Pull the implementation without losing devbox state

All commands below run inside the devbox, from its repository root. Substitute its real path if it is not `~/posthog`.

```sh
cd ~/posthog
git status --short --branch
git remote get-url origin
git fetch origin signals/scout-live-experiments
```

Preserve existing edits and the current branch before switching. Do not reset, clean, automatically stash, reseed or delete volumes. If another session owns the checkout, coordinate the switch; a second worktree alone does not isolate ports, databases or Temporal workers.

With a clean checkout, create a local iteration branch:

```sh
git switch -c scout-devbox-evals --no-track origin/signals/scout-live-experiments
git merge-base --is-ancestor b56358a961ee70992b30840a7fddb38b4b7841ab HEAD
git rev-parse HEAD
.codex/with-flox --prepare true
```

If `scout-devbox-evals` already exists, inspect and resume it instead of recreating it. Run environment-dependent commands through `.codex/with-flox`; request tool elevation on the first attempt for preparation, dependency changes and service lifecycle commands. Use the repository's existing `run-posthog` and `setting-up-devbox` skills when needed.

Keep observations, exports, prompts and credentials outside Git. For example, use `~/.local/state/posthog/scout-evals/`, with directory mode `700`, and separate subdirectories per batch. Create a local `RUNBOOK.md` there containing the branch/SHA, synthetic project and operator IDs, source config ID, data scenario/version, process URLs, local patches, run IDs and budget ledger. Do not print credentials into it.

## 2. Inspect the existing project and the access gates

Before changing services, record which project holds the synthetic data, its parent project if any, and which user will launch runs. Check that the relevant data is queryable through PostHog and that its timestamps match the scout's investigation window. A running UI alone does not prove ClickHouse data is ready.

Scout configuration resolves to the canonical parent project. For a child environment, verify the actual tool queries reach the intended synthetic dataset. Any local access override must account explicitly for both the requested UI project and the canonical config/context project.

The current comparison UI, setup/history APIs, scoring API **and scoring worker require a staff user in project 2**. Staff status alone does not replace organization membership, project access or skill editor permission.

- If project 2 already holds the synthetic data, use it and a local staff operator with the required access.
- If the data is elsewhere, keep it there. Make a small, explicit devbox-only access adaptation before testing the complete flow. Do not renumber project rows or move data into an empty project just to expose the page.
- The adaptation must cover `trial_views.py::_internal_trial_config`, `trial_evaluation.py::_assert_context_access`, `ScoutTrialsScene.tsx`, `ScoutsRosterActions.tsx`, and the inner `ScoutTrials.tsx` guard. Search for all project-2 checks before editing.
- Retain staff, current membership, project/skill access, launching-operator ownership and sandbox restrictions. A backend exception must require `DEBUG` plus an explicit local project allowlist, default off. Keep frontend visibility consistent with the backend. Verify an unrelated project and another user still cannot read the results.
- This local override does **not exist** in the implementation commit. Record its patch separately and do not publish an unrestricted gate removal as a feature fix.

The broader trial launch API is not a workaround for scoring permissions: it can launch a run in a project that the scoring worker later rejects.

## 3. Make the real execution path ready

Preserve the devbox's existing ingestion and synthetic traffic setup. Inspect the current process configuration before changing it:

```sh
.codex/with-flox hogli dev:explain
.codex/with-flox hogli dev:list-units tasks
.codex/with-flox hogli dev:list-units mcp
.codex/with-flox hogli doctor
```

Required processes are backend, frontend, MCP, the **Python** LLM gateway, Temporal server and worker, Docker agent sandboxes, PostgreSQL, ClickHouse, Redis and object storage. `tasks` supplies the task/gateway workers; MCP needs the separate `mcp` intent. `ai_features` also needs `mcp` separately. If using `hogli dev:apply`, supply the complete previous intent list plus the missing intents: the command replaces the list.

The normal local stack performs migrations on startup. Check its PostgreSQL and ClickHouse migration units and apply any outstanding migrations using the existing setup. Preserve the synthetic database. SeaweedFS object storage must be ready, including its configured credentials; the evaluation uses private write-once objects as well as task state.

### Local routes and configuration

Inspect actual listeners first. The following are the usual addresses when app processes run on the devbox host and agents run in Docker:

```dotenv
SANDBOX_PROVIDER=docker
SANDBOX_API_URL=http://host.docker.internal:8000
SANDBOX_MCP_URL=http://host.docker.internal:8787/mcp
SANDBOX_LLM_GATEWAY_URL=http://host.docker.internal:3308
LLM_GATEWAY_URL=http://localhost:3308
```

Retain the existing public `SITE_URL` for browser access. A sandbox cannot authenticate through the devbox's browser sign-in proxy. `localhost` inside a sandbox means that container, not the devbox host. Verify Docker's host mapping and actual connectivity; adjust ports if this devbox differs.

Use the existing local development configuration. `DEBUG=true` with `CLOUD_DEPLOYMENT=US`, `EU` or `DEV` is deliberately rejected. Do not configure a local box as a production region to obtain missing capabilities.

The gateway process must run this branch's `services/llm-gateway` code and authenticate against the **local** database. Use the normal `llm-gateway` unit, not a second private gateway. Trial credentials select private capture themselves. A healthy older gateway or the Go gateway is not equivalent.

Verify configured provider keys through the gateway's supported secret plumbing. Its settings use the `LLM_GATEWAY_` prefix, including `LLM_GATEWAY_OPENAI_API_KEY` and, when needed for the scout model, `LLM_GATEWAY_ANTHROPIC_API_KEY`. The current comparison judge uses **`gpt-5.5`**; scout model support comes from `trial_setup`. Provider reachability and authorization both need a real request.

`.codex/with-flox` builds a minimal environment and loads the repository dotenv file. Do not assume shell-exported credentials or new `.env.local` values reach every manual command. Hogli loads `.env.local`; standalone `bin/start-llm-gateway` also sources root `.env`. Use the established ignored configuration files and verify effective settings without dumping the environment or key values.

MCP has a second routing trap: `bin/start-mcp-server` rewrites its `.env` API address from public `SITE_URL`. For sandbox calls, explicitly configure the MCP process with `POSTHOG_API_BASE_URL=http://localhost:8000` and `POSTHOG_PUBLIC_URL` equal to the existing public app URL. Preexisting process variables take precedence over the service dotenv file. If a process override is needed, its command can use:

```sh
.codex/with-flox env \
  POSTHOG_API_BASE_URL=http://localhost:8000 \
  POSTHOG_PUBLIC_URL='<existing devbox public app URL>' \
  bin/start-mcp-server
```

Replace the placeholder and install the command in the existing process manager; do not start a competing MCP listener. Configure all telemetry destinations outside the synthetic project being investigated, or disable capture during quality iteration. Clear placeholder analytics keys in the MCP example configuration. Global capture disablement does not prove request-specific private suppression.

### OAuth, worker and sandbox preparation

After local migrations and configuration are ready:

```sh
.codex/with-flox python manage.py setup_tasks_oauth
.codex/with-flox python manage.py register_temporal_search_attributes
```

`setup_tasks_oauth` creates the Signals application with the canonical local identity. `setup_background_agents` alone is insufficient. If setup warns that an existing OAuth application has a different primary key, diagnose it; deleting the row also deletes its tokens.

If the ordinary local gateway credential is missing, with `CLOUD_DEPLOYMENT` unset, provision its scope using `.codex/with-flox python manage.py setup_local_api_key --add-scopes llm_gateway:read >/dev/null`. Output is suppressed because this command prints the key. It rejects even `CLOUD_DEPLOYMENT=E2E`. This development key can belong to a different user; it is separate from the operator key used for trial APIs.

Check only nonsecret facts:

```sh
.codex/with-flox python manage.py shell <<'PY'
from django.conf import settings
from posthog.temporal.oauth import SIGNALS_APP_ID_DEV, get_signals_app

assert settings.DEBUG
assert settings.CLOUD_DEPLOYMENT not in {"US", "EU", "DEV"}
app = get_signals_app()
assert app is not None and str(app.id) == SIGNALS_APP_ID_DEV
assert settings.VIDEO_EXPORT_TASK_QUEUE == "development-task-queue"
assert settings.TASKS_TASK_QUEUE == "development-task-queue"
assert settings.SANDBOX_JWT_PRIVATE_KEY
print("Local OAuth, queues and sandbox signing configuration verified.")
PY
```

The normal local `temporal-worker` registers both scout execution and comparison judging. There is no new evaluation queue to provision. Confirm that the running worker uses this checkout, not an older branch.

If the sandbox image needs preparation, build it before a paid run:

```sh
.codex/with-flox python manage.py shell <<'PY'
from products.tasks.backend.logic.services.docker_sandbox import ensure_fresh_base_image
ensure_fresh_base_image()
PY
```

Once the branch's gateway policy, local endpoints and capture destinations are checked, set these values on **both backend and worker**:

```dotenv
SCOUT_LIVE_TRIALS_ENABLED=true
SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=true
```

The second setting is an operator attestation, not a capability probe or a telemetry configuration switch. Restart the devbox app supervisor after environment changes so its children receive the new values. A normal restart keeps database volumes:

```sh
.codex/with-flox hogli down -y
.codex/with-flox hogli up -d -y
.codex/with-flox hogli services:ready -y
.codex/with-flox hogli wait -y
curl -fsS http://localhost:8010/_health
curl -fsS http://localhost:3308/_readiness
```

Use process-specific logs when the broad wait reports unrelated failures. Readiness does not verify provider authentication. If private routing fails its first real test, disable new trial launches until corrected.

## 4. Choose one supported scout and run a small smoke test

Use an existing scout over the synthetic data, or create one through the local scout editor with a small, bounded task. Keep scheduled runs off during the experiment. The simplest first scout has no repository dependency.

The source skill must support report output through `emit_report` or `edit_report`. Trials currently reject extra product `write_scopes`, external `mcp_gateway_server_ids`, and `structured_output_schema`. Preserve those checks. Enable the local organization's required AI consent and source configuration where missing.

Open `<devbox app URL>/project/<project_id>/inbox/scouts/comparisons` as the operator. Select the source scout and inspect:

```text
GET /api/projects/<project_id>/signals/scout/configs/<config_id>/trial_setup/
```

Require `ready: true`. Read `blocked_reason` otherwise. Fleet enrollment, source/skill permissions, spend quotas and daily run budgets remain active. Resolve the local cause instead of deleting checks or editing production feature flags. `signals-scout` enrollment comes from the SDK flag payload; adding a similarly named flag in an arbitrary project does not necessarily change that payload.

Choose a model and effort from the returned `models` list. If the source effort is null, set it explicitly. Record the source skill version, prompt hash, model, effort and data window.

1. Remove the default **Variant 1** row and set repeats to **1**, then launch one short baseline run against a known synthetic finding.
2. Wait for a valid completed result and inspect the captured report, memory and tool evidence.
3. Choose **Score comparison** once. This starts a separate paid judge call.
4. Wait for the saved report. Inspect actual verdicts and source quotations; a report consisting of judge errors is not successful validation.
5. Reload the page and export the report. Confirm it reads the same evaluation without another model call.
6. Launch a small baseline/candidate pair sharing the starting context. Confirm separate writable memory and reports, and that the source scout's instructions/shared memory and normal inbox remain unchanged.

Also check a second local user cannot read the operator's trial tasks/results, and each sandbox's ordinary scoped calls cannot access its sibling's private state. Inspect only credentials issued through normal application interfaces; never scrape other processes for tokens.

For capture acceptance, compare one synthetic ordinary gateway call with one trial call using a separate telemetry destination: the ordinary call retains expected capture, the private call suppresses content, and both retain spend/rate-limit enforcement. Include provider-library stderr logs, background stream failures, and exception events in this check; all ordinary gateway events use the configured capture host. Global capture-off plus an empty event list is insufficient evidence. Record any unverified part explicitly.

Verify that interrupted scout streams on the standard Anthropic route fail in the client instead of returning a partial answer as complete. The gateway requires a complete `message_stop` event for Signals requests on that route and sends a generic Anthropic error when the stream ends early; the initial HTTP 200 alone does not prove completion.

## 5. Repeatable API/CLI alternative

The existing CLI launches, resumes, polls and downloads results/logs. **It does not score.** Prefer the UI for the first complete loop.

Create a private `variants.json` beside a full candidate skill body:

```json
[{ "label": "baseline" }, { "label": "candidate", "skill_file": "candidate.md" }]
```

`skill_file` is relative to that JSON file and replaces the complete skill body. Optional fields are `model`, `reasoning_effort` and `skill_body`; do not combine `skill_body` with `skill_file`.

The CLI reads an operator personal API key from `POSTHOG_API_KEY`. It needs the selected project's scout and skill read/write scopes plus `task:read` for log downloads. Cancellation through the Tasks API separately requires task write access. Keep the key in the devbox's private secret storage. One option is a mode-`600` file at `~/.config/posthog/scout-devbox.pat`, containing the key on one newline-terminated line; load it **inside** the wrapper so environment filtering cannot discard it:

```sh
.codex/with-flox bash -c '
  IFS= read -r POSTHOG_API_KEY < "$HOME/.config/posthog/scout-devbox.pat" || exit 1
  export POSTHOG_API_KEY
  exec python "$@"
' scout-trials \
  products/signals/eval/experiments/2026-09-long-running-agent-evals/scripts/run_live_trials.py \
  --host http://localhost:8000 \
  --project-id '<project_id>' --config-id '<config_uuid>' \
  --variants "$HOME/.local/state/posthog/scout-evals/variants.json" \
  --effort '<supported_effort>' --repeats 2 --concurrency 2 \
  --note '<same bounded investigation instructions for both variants>' \
  --output "$HOME/.local/state/posthog/scout-evals/batch-001"
```

Replace the angle-bracket placeholders. The output directory must be private (mode `700`) and outside Git or ignored. Use local HTTP only for `localhost`/`127.0.0.1`; other hosts require HTTPS. Redirects are rejected.

A timeout does not cancel server runs. Resume with the same secret-loading wrapper and script, passing only the same `--host`, `--output`, and `--resume`. The manifest preserves launch IDs and the shared context; do not regenerate IDs to retry an uncertain submission.

For each saved launch, inspect:

```text
GET /api/projects/<project_id>/signals/scout/configs/<config_id>/trial_result/?launch_id=<launch_uuid>
```

All selected runs must be terminal: `completed`, `failed`, `cancelled`, or `skipped`. Inspect `error`, `invalid_reason`, `export_error` and `task_status`; a failed controller can leave its underlying task active. Task completion alone does not make a result ready: polling and scoring wait for the scout's final export or a terminal controller before recovering a missing export. A task can show `completed` while its trial remains `in_progress` or `unknown` during finalization. Conversely, a saved completed scout result can precede task shutdown; polling keeps it `in_progress` and scoring waits until the task finishes. A failed or cancelled task cannot become a successful comparison through an earlier completed export.

Create and save an explicit scoring request before sending it:

```json
{
  "evaluation_id": "<new evaluation UUID>",
  "baseline_variant_id": "<baseline variant UUID>",
  "rubric_source": "mock",
  "variants": [
    {
      "id": "<baseline variant UUID>",
      "label": "baseline",
      "launch_ids": ["<baseline launch 1>", "<baseline launch 2>"]
    },
    {
      "id": "<candidate variant UUID>",
      "label": "candidate",
      "launch_ids": ["<candidate launch 1>", "<candidate launch 2>"]
    }
  ]
}
```

Submit that body through authenticated `POST .../trial_evaluation/`, then poll `GET .../trial_evaluation_result/?evaluation_id=<evaluation_uuid>`. Use the same config base path as above. The response contains `request`, `evaluation_id`, `context_id`, `status`, `error` and `report`. GET never starts a judge.

Group launches from the known variant specification and repeat count, not by parsing display labels. The CLI manifest is variant-major, then repeat order. Limits are 10 variants and 20 distinct launches total. All runs must share scout, operator and starting context; settings must match within each variant.

Retrying the same evaluation ID requires the exact saved request. It reuses saved work and does not automatically repeat an attempted paid call. **New scoring attempt** uses a new evaluation ID and may charge for every included run again. It preserves the previous report.

## 6. Iterate on scout quality and judge quality separately

Prepare a small synthetic case set using the existing data generator/fixtures. Keep an answer key outside the scout prompt and the judge's evidence. Do not build another generic eval framework.

| Case                              | Check against the synthetic truth                                                               |
| --------------------------------- | ----------------------------------------------------------------------------------------------- |
| Clear finding                     | The scout finds the planted issue, cites the right records and proposes a proportionate action. |
| Quiet period                      | The scout avoids inventing a finding or overstating weak evidence.                              |
| Known issue/history               | Relevant prior memory prevents duplicates; a material change is explained.                      |
| Distractor or incomplete evidence | The scout distinguishes uncertainty from a supported claim.                                     |

Record expected findings, relevant synthetic record IDs, acceptable actions/priorities and known false positives **before** looking at results. Check that the seed actually created these facts in queryable data; a scenario description is not proof of successful ingestion.

For each iteration:

1. Keep the data stable within a comparison. Shared context freezes initial history, not live project reads or the clock. Pause changing synthetic traffic if appropriate, or record its schedule and exact time window. Restore it afterward.
2. Run two variants with two repeats per scenario initially. Change one scout prompt/model/effort dimension at a time, using the same investigation note. Start a fresh context for each independent scenario.
3. Read the scout output and raw evidence, then label the criteria manually before opening the evaluation report with its judge verdicts. Record missed planted findings and false positives against the answer key separately.
4. Compare the judge's passes, failures and unknowns with those labels. Investigate unsupported passes and missing tool evidence before tuning prompts for a higher score.
5. When changing only the judge/rubric, reuse completed scout runs under a **new evaluation ID**. When changing the scout or data, run a new comparison.
6. Confirm promising scout changes on held-out scenarios and additional repeats within budget. Report results by scenario, including execution failures and cost uncertainty.

The run score is `pass / (pass + fail)`. The variant score is the equal mean of non-null run scores. Coverage is `(pass + fail) / (pass + fail + unknown)`; not-applicable criteria are excluded. Execution failures and judge errors are separate from quality. Baseline differences appear only for fully comparable outcomes.

A high score with low coverage is not strong evidence. The judge checks bounded saved evidence and exact quotations; it does not independently query source truth or measure recall. Use the synthetic answer key to measure missed findings and false positives. These small live comparisons do not establish statistical significance.

### Where to make changes

| Change                                       | Source                                                                                                                   |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Scout prompt/model/effort                    | Comparison variant inputs; preserve a baseline and source skill.                                                         |
| Mock criteria                                | `products/signals/backend/scout_harness/mock_scout_rubric.json`                                                          |
| Mock reader / future real-reader integration | `trial_rubrics.py`; reader construction in `trial_evaluation.py::prepare_trial_evaluation`                               |
| Judge instructions and citation parsing      | `trial_judge.py`                                                                                                         |
| Judge model and saved prompt version         | `trial_evaluation.py`; keep prompt-version compatibility in `trial_judge.py` synchronized.                               |
| Scores, coverage and comparison eligibility  | `trial_evaluation_report.py`                                                                                             |
| Paid-call claims and saved state             | `trial_evaluation.py`, `temporal/agentic/scout_trial_evaluation.py`                                                      |
| UI state and report display                  | `frontend/inbox/logics/scoutTrialsLogic.ts`, `frontend/inbox/components/config/scouts/trials/` under `products/signals/` |

The mock uses six default criteria, `revision: 0`, and `generation: null`; only enabled criteria are judged. New evaluation IDs freeze the exact rubric document, evidence, model and prompt version. Changing a fixture never rewrites an existing report. Record code and fixture hashes; bump the prompt version when judge behavior changes.

The future real reader should consume `GET /api/projects/{team_id}/signals/scout/rubrics/{config_id}/` from the rubric feature. Only `rubric_source: "mock"` is accepted today. Real integration needs coordinated API types and UI provenance, and must propagate unavailable/access errors instead of silently falling back to the mock.

## 7. Debug and validate changes

| Symptom                                          | First checks                                                                                                                        |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Comparison page/setup/scoring returns 404        | Project-2 gates, staff status, operator membership and skill access; include worker checks.                                         |
| `ready: false` or immediate rejection            | Read `blocked_reason`; verify both flags, source capabilities, enrollment, quotas and selected effort.                              |
| Run remains queued                               | Correct branch in Temporal worker, development queue registration, sandbox image and Docker access.                                 |
| Sandbox sees HTML/login instead of API JSON      | Public proxy/Coder route used for backend, MCP or gateway; check direct sandbox URLs and MCP upstream.                              |
| Gateway 401/403                                  | Local Signals app identity, local token database, token scope/expiry and provider authorization; health endpoints are insufficient. |
| Results complete but logs return 403             | Operator key lacks `task:read`, or the caller is not the original operator.                                                         |
| Scoring fails or reports only judge errors       | Judge model access, gateway credentials, worker logs, immutable saved attempt. Fix before explicitly paying for a new attempt.      |
| Scores mostly unknown                            | Read evidence limitations and trace extraction; do not convert missing evidence to a pass.                                          |
| Object-store `InvalidAccessKeyId`                | Wait for SeaweedFS credential readiness; confirm the processes share the intended local store.                                      |
| Frontend types miss a newly added quill property | Rebuild the local package with `.codex/with-flox pnpm --filter=@posthog/quill-components build`.                                    |

For backend changes, start with the relevant existing tests, for example:

```sh
.codex/with-flox uv run pytest \
  products/signals/backend/test/test_scout_trial_evaluation.py \
  products/signals/backend/test/test_scout_trial_evaluation_report.py \
  products/signals/backend/test/test_scout_trial_judge.py \
  products/signals/backend/test/test_scout_trials_api.py \
  products/signals/backend/test/test_scout_trial_state.py \
  --reuse-db -q
```

Use an isolated test database/Redis configuration, not destructive test setup against the seeded application database. Serialize suites sharing the same test database. If this is a cloud task environment, follow `docs/internal/cloud-task-sandbox.md` first.

Run affected frontend tests and render UI changes. For type-risky Python changes, run repository-wide mypy. Regenerate OpenAPI after serializer changes. Follow `running-ci-preflight` before committing/pushing; never bypass hooks. Keep devbox-only configuration, tokens and runtime artifacts out of source commits. Report a broken local workflow through the repository's devex feedback command when applicable.

## Completion and next handoff

Leave the devbox usable, with synthetic data intact and temporary generator pauses restored. Record:

- The exact code revision, local setup/access patches, source scout and synthetic scenario versions.
- At least one completed real scout run and a saved real judged comparison, with IDs, JSON exports and supporting evidence.
- Confirmation that reload/retry does not create unintended paid calls; private results remain isolated.
- A baseline/candidate result by scenario, human/judge disagreements, missing findings and false positives.
- Actual or bounded spend, unknown charges, remaining budget and any unverified acceptance check.
- The next concrete quality improvement to try, with a command or saved comparison request that resumes the work.

If the model request cannot authenticate, or scoring only produces errors, mark the end-to-end milestone incomplete. Preserve the saved IDs and diagnose the setup before running more comparisons.

References: [live comparison and scoring semantics](ai-offline-evaluation-reporting.md#live-scout-comparisons), [implementation plan and operator script](../../products/signals/eval/experiments/2026-09-long-running-agent-evals/PLAN.md), [run-posthog skill](../../.agents/skills/run-posthog/SKILL.md), [devbox skill](../../.agents/skills/setting-up-devbox/SKILL.md).
