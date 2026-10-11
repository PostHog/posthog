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

Switching the flag off blocks new trials, resumes, queued scout work and new judge dispatch. Judges already dispatched to Tasks can finish, even if their sandbox has not started yet. Saved results remain readable.

Verify the ports and Docker host mapping. Sandbox URLs and MCP's `POSTHOG_API_BASE_URL` must reach services directly, without the Coder login proxy. Keep `POSTHOG_PUBLIC_URL` and `SITE_URL` on the browser URL.
The backend and scout orchestration worker use their existing `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY`. Private report checks mint and revoke temporary tokens with that service credential. Only the Tasks worker that provisions sandboxes needs `SANDBOX_AI_GATEWAY_URL` and `SANDBOX_AI_GATEWAY_MINT_KEY`. Both credentials must allow private token creation and team attribution in the intended paying project. The `signals_scout` product must not bill customer credits.
API-side token calls bypass environment proxies, matching the other service gateway clients. Sandbox token calls keep their existing proxy behavior.
Enable `SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE` only after confirming query/task telemetry and warehouse replicas do not expose trial content to the inspected project. The gateway must acknowledge capture suppression when minting tokens.
This setting also installs the private-trial analytics filter when backend and worker processes start. Leave it enabled while saved trial data remains accessible, even after disabling new launches or the `scout-trials` flag. Deployments without this setting keep their existing analytics callbacks.
Deploy the backend, scout orchestration worker and Tasks worker from the same code revision before enabling trials; use `TEMPORAL_DISABLE_HOT_RELOAD=1` during paid runs. The scout worker uses the video-export queue. The Tasks worker provisions the sandboxes. Removing the old Tasks validation does not change the ordinary judge path, but new scout launches require the updated Tasks worker.
Revoke or expire private tokens before rolling the gateway back to a version without private capture support.

## Run through MCP

1. Find an existing scout with `scout-config-list`, or create an idea to test with `scout-create` and `config.enabled=false` so scheduling does not interfere.
2. Call `scout-trial-setup` for readiness, source version, and supported model/effort choices.
3. Read `scout-rubric-get`. If generation is needed, call `scout-rubric-generate` and poll `scout-rubric-get`; inspect the suggestions, summary, and captured `generation.reference_context`.
4. Use `scout-rubric-save` with the latest `revision` and complete selected criteria, retaining all default IDs. Set `adopt_generation_id` to the current completed `generation.id` to adopt its reference; generation alone does not save or adopt it.
5. Call `scout-trial-start` with a baseline and variants, stable comparison/variant/launch UUIDs, and `expected_skill_version`. Each variant can replace its `skill_body`; the optional `note` steers every run. Retain the exact request for retries.
6. Poll `scout-trial-report` through execution and judging, then inspect criterion evidence, failures, coverage, and cost before drawing conclusions.

`scout-trial-list` returns progress and IDs; fetch judgments with `scout-trial-report`. Use `scout-trial-resume` to recover an interrupted plan and `scout-trial-archive` to hide or restore finished trials.
The lower-level `scout-trial-create` / `scout-trial-get` pair runs a single private scout without automatic judging. A trial does not apply a candidate or enable scheduling; agents can do that with `skill-update` and `scout-config-update` when part of the requested work.
See the [scout authoring reference](../../products/signals/skills/authoring-scouts/references/lifecycle-and-testing.md#private-trials-with-a-saved-rubric) for selection, adoption, and comparison details.

## Run one trial

1. Open `/project/2/inbox/scout-trials`, search for and select the scout, then select **New trial**. Resolve any setup blocker shown. The picker lists scouts by display name; the old `/project/2/scout-trials` address redirects here. Trials have a separate path so existing scout names remain valid.
2. Start with two versions and one run per version. Change the second version's model, effort or prompt.
3. Select **Start trial**. Runs show **Queued** while an active trial starts them; this is not a failure. Scouts run and judging follows automatically; closing the page does not stop them.
4. Compare the results, then open a run to inspect its report and evidence for each rubric check. Cost and speed are shown separately from rubric results.
5. Reopen the saved trial or export its JSON report. Reading saved results makes no further model calls.

The rubric stays fixed across scout edits, and saved results retain the rubric used for that trial. If a run is interrupted, reopen the existing trial before starting another paid attempt.

History shows 30 trials per page, with previous and next controls for older results. Archive a completed or failed trial to hide it from history. Show archived trials to view their saved reports or restore them; archiving never deletes evidence or stops a running trial. Archive and restore remain available when the trials flag is off, with the same access checks. Open a trial to see its individual runs. Run-detail loading errors appear beside the affected run with a retry action, while the history page continues to show saved results.

Trial scouts have a 30-minute runtime limit. Regular scouts keep their 15-minute limit. Timed-out scouts cannot be scored; their run details and scoring exclusion explain the timeout. Start a new trial to try again.

Trial scout deadlines include five minutes for startup and log reads, plus time to collect and save the final result.

Trial plans and evaluation documents keep one complete adopted reference each and exclude suggestion-generation history. The judge reads that same adopted reference from its evidence attachment.

Suggestion generation captures the complete scout instructions and reference files for judging, while keeping the generator's prompt bounded. If an older saved reference is incomplete, generate suggestions again, review and use the new reference, then save. You can keep your existing criteria.
The generator flags unresolved conflicts in the source instructions in its summary instead of choosing a stricter rule. Wording updates to shared defaults affect unsaved rubrics only; saved criteria stay fixed.

Variants and retries share a saved copy of the project's scout memory, notes and recent scout runs. This starting context lives in private object storage and can exceed the 16 MiB limit on launch settings without being shortened.

Each trial scout stores its own memory changes and reports in a separate `trial_state` field on its Signals scout-run record. The small trial marker stays in metadata so ordinary history queries can exclude trials without reading their documents. Tasks run state contains execution settings and token bindings, not trial documents. Signals verifies the sandbox token belongs to that exact run before serving private context. Tasks grants the restricted scout credential only the necessary log, summary and lifecycle writes for its own run; it cannot change another task or steer a trial. Ordinary scout responses omit the private state.

Trial scouts can use `created_after`, `priority`, `actionability`, and `already_addressed` on `inbox-reports-list`. Report edits, including priority and actionability changes, stay private to the individual run and appear in its subsequent reads; they never modify shared reports or another trial run. Ordering by ranking scores is refused explicitly because private report edits have not been ranked.

Each completed scout run gets its own judge sandbox. The judge reads the saved rubric and searches attached copies of the complete rubric reference, run log, reports, summary, candidate instructions and starting context. These files live in private object storage; Temporal receives only their identifiers. Evidence larger than 128 MiB is refused explicitly instead of being silently shortened.

Signals checks the operator's access, source run and saved evidence before attaching files and dispatching the judge through the existing internal Tasks path used by rubric generation. Queued judges do not repeat Signals-specific staff, skill or source-run checks at sandbox startup. Ordinary account and project permissions still apply when downloading evidence, and Signals checks operator access again before publishing the report.

Judges use ordinary Tasks permissions and logging rather than the scout runs' private credentials and capture suppression. Other sandboxes acting as the same operator in the same project can read judge prompts and attached evidence through the Tasks API.

Scout sandboxes keep private gateway capture and exclude shared context-layer inputs. Tasks no longer calls Signals to interpret trial documents or judge credentials. Shared dispatch preparation, file attachments and budget-stop handling remain unchanged.

The judge has no live project tools, external MCP connections or repository credentials. Its run disables live context, so the Tasks worker neither mounts the current wiki nor adds Store skill descriptions. Internal Tasks also exclude project and personal instructions. Deploy the Tasks worker's support for this run setting before starting new judges.

The judge saves one JSON verdict per rubric check through Tasks' existing structured-output support. Signals checks that same Task until it finishes, then validates its quotes against the original saved files. New evaluations use saved scout identifiers to recheck current permissions on every status poll without downloading the full starting context again; preparation and report finalization still validate that context. Worker restarts resume result collection without starting another judge. If result collection remains unavailable, the evaluation fails without freezing an incomplete report; resuming the same evaluation reuses its Tasks and saved judgments.

The judge first checks whether each criterion applies, including allowed exceptions and optional work. The required skill and project-profile startup reads are distinguished from the investigation itself; incidental metadata in those responses does not by itself prove unrelated investigation. Required step order is checked against the execution timeline; doing both steps in the wrong order does not satisfy it. Unresolved conflicting instructions give an unknown verdict unless another clear violation already fails that criterion. Judge prompt versions are fixed per trial: after a version changes, unfinished trials using the older judge require a new trial. Resuming an outdated trial is rejected before more paid runs start. Completed reports stay readable.

Unavailable or ambiguous evidence gives an unknown verdict. A required action proved missing from a complete record fails; missing thoughts alone never prove an omission. Citation checks accept decoded JSON string fields in tool responses. A judge failure is shown separately from a failed rubric check. Each judge has a 30-minute deadline measured from its original Task run creation; retries do not reset it. Up to three collectors run at once, but judge Tasks can briefly overlap beyond that after a delayed start or collection failure. Saved results never rerun the judge when viewed.

Only versions whose runs all completed and were judged can lead. At least two completed versions with the same number of runs are needed; failed versions remain visible and are excluded even if most versions failed. The result compares completed versions by their total confirmed rubric passes. Unknown checks earn no passes and make any leader or tie provisional. Without a confirmed pass, unresolved checks cannot produce a leader. Final winners still require comparable applicable checks. Saved reports retain their original conclusions.

Before dispatch, the full batch must fit the project's existing daily scout budget. Resuming counts only runs that have not already started. This is a capacity check, not a reservation: simultaneous submissions can still race, and the budget remains shared with ordinary scouts.
