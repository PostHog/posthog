# Online scout trials in a devbox

Trials run scout versions in parallel, then judge them against the same saved rubric. Versions can change the prompt, model or reasoning effort.

## Before starting

Follow the existing [devbox setup](../../.agents/skills/setting-up-devbox/SKILL.md) and [local stack](../../.agents/skills/run-posthog/SKILL.md) instructions.

- Use a staff user with membership in project 2 and permission to edit the source skill.
- Choose a scout with a reviewed, saved rubric and report tools (`emit_report` or `edit_report`). The trial setup screen explains unsupported configurations.
- Start MCP, Temporal and Docker sandboxes alongside the normal stack. Complete local OAuth setup (`setup_tasks_oauth`) and Temporal search-attribute registration.
- Use the [Go AI gateway](https://github.com/PostHog/ai-gateway), with credentials for the scout models and the judge model, currently `gpt-6-astra`.
- Preserve the synthetic dataset and set a test budget: scouts and judging make paid model calls. Keep credentials and downloaded reports outside Git.

## Configuration

Deploy support for private scoped tokens (`capture_mode: none`) to every gateway replica before enabling trials. Configure the local stack as follows; service-specific credentials are described below:

```dotenv
SANDBOX_PROVIDER=docker
SANDBOX_API_URL=http://host.docker.internal:8000
SANDBOX_MCP_URL=http://host.docker.internal:8787/mcp
SANDBOX_AI_GATEWAY_URL=http://host.docker.internal:8080
AI_GATEWAY_URL=http://localhost:8080/v1
SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=true
```

Enable the `scout-trials` feature flag for the `project` group with `id = 2`. A missing or unreadable flag blocks new work. Trials also require private capture and the gateway configuration above. The team-2 and staff restrictions still apply even if the flag targets another project. Production MCP also hides trial tools until the flag is enabled.

Switching the flag off blocks new trials, resumes, and queued scout or judge work. Already-running scouts and judge jobs can finish, and saved results remain readable. After re-enabling the flag, resume interrupted trials to recover saved work.

Verify the ports and Docker host mapping. Sandbox URLs and MCP's `POSTHOG_API_BASE_URL` must reach services directly, without the Coder login proxy. Keep `POSTHOG_PUBLIC_URL` and `SITE_URL` on the browser URL.
The backend and scout orchestration worker use their existing `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY`. Private report checks mint and revoke temporary tokens with that service credential. Only the Tasks worker that provisions sandboxes needs `SANDBOX_AI_GATEWAY_URL` and `SANDBOX_AI_GATEWAY_MINT_KEY`. Both credentials must allow private token creation and team attribution in the intended paying project. The `signals_scout` product must not bill customer credits.
API-side token calls bypass environment proxies, matching the other service gateway clients. Sandbox token calls keep their existing proxy behavior.
Enable `SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE` only after confirming query/task telemetry and warehouse replicas do not expose trial content to the inspected project. The gateway must acknowledge capture suppression when minting tokens.
This setting also installs the private-trial analytics filter when backend and worker processes start. Leave it enabled while saved trial data remains accessible, even after disabling new launches or the `scout-trials` flag. Deployments without this setting keep their existing analytics callbacks.
Keep the worker and backend on the same code revision; use `TEMPORAL_DISABLE_HOT_RELOAD=1` during paid runs.
Revoke or expire private tokens before rolling the gateway back to a version without private capture support.

## Run one trial

1. Open `/project/2/scout-trials`, select **New trial**, and choose the scout. Resolve any setup blocker shown.
2. Start with two versions and one run per version. Change the second version's model, effort or prompt.
3. Select **Start trial**. Scouts run and judging follows automatically; closing the page does not stop them.
4. Compare the results, then open a run to inspect its report and evidence for each rubric check. Cost and speed are shown separately from rubric results.
5. Reopen the saved trial or export its JSON report. Reading saved results makes no further model calls.

The rubric stays fixed across scout edits, and saved results retain the rubric used for that trial. If a run is interrupted, reopen the existing trial before starting another paid attempt.

Trial plans and evaluation documents keep one complete adopted reference each and exclude suggestion-generation history. The judge reads that same adopted reference from its evidence attachment.

Suggestion generation captures the complete scout instructions and reference files for judging, while keeping the generator's prompt bounded. If an older saved reference is incomplete, generate suggestions again, review and use the new reference, then save. You can keep your existing criteria.

Variants and retries share a saved copy of the project's scout memory, notes and recent scout runs. This starting context lives in private object storage and can exceed the 16 MiB limit on launch settings without being shortened.

Each completed scout run gets its own judge sandbox. The judge reads the saved rubric and searches attached copies of the complete rubric reference, run log, reports, summary, candidate instructions and starting context. These files live in private object storage; Temporal receives only their identifiers. Evidence larger than 128 MiB is refused explicitly instead of being silently shortened.

The judge has no live project tools, external MCP connections or repository credentials. It returns one verdict per rubric check, with quotes checked against the original saved files. Missing evidence gives an unknown verdict. A judge failure is shown separately from a failed rubric check, and incomplete results cannot win. Judging has a 15-minute runtime limit per run; saved results never rerun the judge when viewed.

Before dispatch, the full batch must fit the project's existing daily scout budget. Resuming counts only runs that have not already started. This is a capacity check, not a reservation: simultaneous submissions can still race, and the budget remains shared with ordinary scouts.
