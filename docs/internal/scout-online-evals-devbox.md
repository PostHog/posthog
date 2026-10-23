# Online scout trials in a devbox

Trials run scout versions in parallel, then judge them against the same saved rubric. Versions can change the prompt, model or reasoning effort.

## Preparing a portable scout environment

Load the shared [creating-scout-eval-environments skill](https://us.posthog.com/project/2/skills/creating-scout-eval-environments)
through PostHog MCP (`posthog:skill-get`). The MCP skill is the source of truth for
data sufficiency, capture limits, validation depth and handoff; do not maintain a
local skill copy. It accepts a saved scout, or a draft skill and target project.
The source exporter preserves supported context, checks complete pagination and
rejects unsupported dependencies instead of filling them with synthetic data.

The existing Parquet `pack` command accepts `--scout-case <private case.json>`.
This produces a version-2 archive containing events, optional governed metrics,
and a checksum-bound scout definition and starting state. The existing
`hogli devbox:prepare-eval-env` flow validates the attachment before startup,
restores and verifies it, then freezes the baseline. Event-only version-1 bundles
continue to work. See the [bundle README](../../products/posthog_ai/eval_harness/environment/README.md)
for command usage and the MCP skill's bundled real-data reference for current API limits,
including the required existing project-profile snapshot.

A source plan can include `companion_skill_names` for skills the scout reads.
The bundle preserves their versions, files, categories, authors and owners, and
verifies their restored content before each trial. Only the primary skill gets
a scout config; importing a companion does not schedule it.
Canonical companion preflight checks the complete staged skill and its files
against the saved content hash before creating database rows.
Starting state can include backing tasks with their archive state and activity
timestamps, work-claim artefacts and pull requests so report ownership and review
state remain linked after IDs are remapped.
Each claim must belong to the artefact's report. Task channels and external
connections still require separate restore support.
A legacy assignment can share its ID with one work-claim artefact for the same
report. All other starting-state record IDs must remain unique.

Declare `source_project_url` in the case and bundle text policy to keep copied
project links inside the restored instance. Preparation binds the exact source
project prefix to the new project and pins its configured site URL in the receipt;
other projects and external links remain unchanged. Legacy assignments and report
task links can retain report ownership and pull-request projections without
copying task credentials or the complete execution environment.

Real-data cases use `prompt_mode="native"`: leave `SCOUT_EVAL_ENVIRONMENT_FILE`
unset so the runner builds its ordinary prompt from restored context. Freeze
still binds the case and harness version; the native `runtime-prompt.json` is a
verification descriptor, not a prompt override. Recorded replay remains explicit
and follows the instructions below.

The preparation helper preserves an existing box's startup setting; it defers
automatic app startup only when creating a box. Follow the MCP skill for the
requested completion checks. Environment preparation and a paid scout trial are
separate outcomes; report the checks actually performed.

## Reconstructing an isolated project from traces

For checkout-based reconstruction, load `creating-scout-eval-environments`
through PostHog MCP. Keep private traces, reconstructed Parquet files, starting scout state,
assumptions and trial exports outside Git or in an ignored directory. The scout
sandbox must not mount that directory.

`python manage.py scout_eval_environment --state-dir <private workspace>` provides
`prepare`, `freeze`, `check`, `run` and `export`. Run it through `.codex/with-flox`
from the repository root. Preparation uses the existing Parquet restore flow and
adds the pinned skill, notes, memory, earlier reports and run history. Freeze the
first reconstruction before inspecting held-out exports or expected findings.
Preserve observed organization gates in the real backing rows, including AI data
processing approval. The importer defaults a new organization to unapproved;
copying an approved cached project profile alone leaves live write checks blocked.
Keep unobserved organization settings as explicit reconstruction assumptions.
Match product feature gates needed by the captured tools too. The existing
`POSTHOG_FEATURE_FLAGS_FORCE_ENABLED` setting accepts an explicit comma-separated
list for the disposable local stack; record those choices with the private case
and restart services after changing them.
Start with task-relevant tool probes. When a required probe fails or masks a
required live dependency behind a cache/fallback, check that dependency directly
using its supported local configuration.
`build-events --recipe <private JSON> --output <new private Parquet>` builds event
rows from the `EventRecipe` schema in `eval_environment/recipes.py`; it refuses
to overwrite an existing file. Record reconstruction assumptions separately.
`extract --run <private run directory> --read-tools <private JSON list> --output
<private observations JSON>` extracts permitted reads from paginated raw logs up
to the first unrecognized operation. Review that boundary for completeness.
An agent combines the observed query results into a saved case and recipe and
declares missing-data choices. Related traces can be reviewed together; rebuilding
from the saved recipe needs no further model calls or trace review. Check this by
building twice and comparing decoded rows before the first restore.

The first restore shifts the data to its target cutoff (near current UTC by default,
with a whole-second shift so timestamps and textual interval bounds stay aligned).
Keep explicit UTC interval bounds in one-time trial steering, shift declared
embedded timestamps consistently, and preserve the project timezone. A restore
receipt is reusable; it does not reset changed state or move its cutoff again.
Clock time continues advancing within a session.
For date-only or minute-only query bounds, supply an explicitly aligned
`--target-cutoff`; their written precision cannot represent a finer shift.

For a local project whose ID differs from 2, set `SCOUT_TRIALS_LOCAL_TEAM_ID` to
the prepared project ID. Only `DEBUG` honors this setting; that exact local
project does not depend on the production trial feature flag. Staff and skill
access checks still apply. Other deployments keep the project-2 gate.

Set `SCOUT_EVAL_ENVIRONMENT_FILE` to the frozen workspace's `runtime-prompt.json`
in the backend and scout worker. The local-only adapter preserves the recorded
full prompt while replacing declared identifiers/timestamps, current run identity
and one-time steering. Frozen-input changes or a mismatched scout fail closed.
The file is read by the worker and is not attached to the sandbox.

For a run that should behave like ordinary scouting, inspect every agent-visible
instruction before launching. A recorded prompt may already disclose a benchmark
or private trial. When rewriting those instructions is authorized, keep the original
prompt privately and declare exact `prompt_transformations` in the case,
including the source text, replacement, reason and expected occurrence count.
Freeze binds those changes; a changed source fails closed. Rewrite the task skill
and steering consistently, retain its scope rules, and keep concrete dates in
one-time steering. Do not tell the scout that its data is real or ask it to ignore
inconsistencies. Isolation remains enforced by the server.

Restore observed project and organization names through the case metadata. Use
an explicitly selected local operator account with `prepare --user-id` when the
importer's default evaluation-labelled login would be visible to the scout.
Record assumptions for missing identities outside the scout context.
Include task-forbidden identity tools in the operator's reconstruction preflight
while keeping them available to the scout so violations remain observable.
Preserve captured names, emails, logins and team memberships through their real
backing state. Check visible responses for automatically generated placeholders;
use source-backed values or explicit private assumptions for missing fields.
Keep public examples and defaults on reserved domains, and never fill missing
identity fields from production.

For requested and authorized execution, start with one standalone trial and
inspect its complete exported log before launching comparisons. Environment-only
preparation stops at the MCP skill's smoke-test handoff. The `run` command plans without paid calls; `--launch`
dispatches the saved IDs. A multi-run plan uses existing Scout comparisons and
their saved rubric judges. Comparison exports include each run's full trace and
private results alongside the saved judge report. Check the export's per-run
errors before treating a trace as complete. Trials isolate their report and
memory writes; the underlying restored project must remain stable for the whole
comparison. Inbox reads preserve `include_unlisted` for both existing reports
and private trial reports, so a scout can search the complete inbox for duplicates.
Before planning or launching, `check` verifies the frozen files, scout state,
local routing, governed metric fields and event counts/minimum/maximum timestamps.
It reads the restored database without repairing it. Event property-level fidelity
still needs independent task-relevant queries; equal aggregate counts and bounds
cannot detect every event edit.
Review tool responses and available reasoning summaries for both evaluation
awareness and suspected fabricated data. Report the exact evidence separately;
an absence of remarks does not establish what the scout believed. For a failed
requested run, follow the MCP skill's repair boundaries and preserve diagnostics.
Keep scout quality changes and comparison batches separate from preparation.
Configured local evaluations also snapshot the starting project profile. A
`force_refresh` call runs the real profile builder, rolls back its shared cache
and pruning writes and background callbacks, then saves the result only in that
trial's private state. Later reads in that run see its refreshed profile; other
runs retain the shared starting snapshot. Ordinary project-profile reads outside
local trial sandboxes keep their existing behavior.

Use one private campaign ledger and reconcile actual usage before another batch.
The ledger reserves configured scout/judge token caps and report-check allowance.
Planning only calculates that allowance. Launch reserves it against a digest of
the complete saved plan, including launch IDs; a pending retry must match exactly.
Settled reservations cannot be reused. Legacy pending reservations without a plan
binding must be reconciled from actual usage before creating a new plan.
Report validation mints additional tokens, so also enforce a campaign-wide gateway
wallet or credential budget. Per-token limits alone are not a global spend cap.
Export results before resetting local databases and use a fresh workspace after
the reset.
Preparation labels the verified capture guard as an event-ingestion policy;
its compiled drop-event behavior and import receipt stay unchanged. The check
command rejects changed labels or changed guard behavior before paid work.
Reconstruction recipes preserve observed rows and accept explicit generated
timestamps. Match the source's timestamp precision and ID format rather than
introducing regular spacing. Set `generated_uuid_version=7` for timestamp-based
generated IDs; the default remains 5. UUIDv7 clock bits encode the source event
timestamp and remain unchanged during the later restore time shift.
Preserve observed list totals, pagination and ordering, and back referenced
objects using captured fields or separately declared assumptions. Map only exact
internal project URL prefixes to the verified local project; preserve external
URLs and unrelated source context.

Restore trace-observed state outside the typed bundle with a private deterministic
seed-and-check adapter using real models and local storage. Finish seeding before
freezing, and pass the event recipe, private builder, assumptions, supplemental
sources and adapter receipt as repeated `freeze --extra-input <private path>`
arguments. These hashes bind the reconstruction choices in both freeze documents;
repeating a freeze requires the same paths and unchanged files. Keep the baseline
immutable once execution starts. The adapter's live-state check remains mandatory
before every run or batch because file hashes do not verify database or
object-storage contents.

Keep the checkout stable during paid runs. Set `TEMPORAL_DISABLE_HOT_RELOAD=1`
and `GRANIAN_RELOAD_IGNORE_PATHS=<absolute checkout root>` before starting workers
and the backend. Otherwise source edits or formatter cache writes can restart the
backend during MCP requests, producing misleading tool failures. Restart through
the normal stack workflow after changing these settings.

When the requested execution needs a fresh baseline, export results before a
data-only reset on the disposable devbox. Use the
existing `hogli down --timeout 20`, `hogli docker:services:remove -y`, and
`hogli up -d -y` flow before preparing into a fresh private workspace. Run those
commands through `.codex/with-flox`. This removes local service data; do not seed
demo data before restoring the trace-derived fixture. `hogli nuke` also reinstalls
dependencies, so it is a broader environment reset.

## Before starting

Follow the existing [devbox setup](../../.agents/skills/setting-up-devbox/SKILL.md) and [local stack](../../.agents/skills/run-posthog/SKILL.md) instructions.

- Use a staff user with membership in project 2 and permission to edit the source skill.
- Choose a scout with a reviewed, saved rubric and report tools (`emit_report` or `edit_report`). The trial setup screen explains unsupported configurations.
- Start MCP, Temporal and Docker sandboxes alongside the normal stack. Complete local OAuth setup (`setup_tasks_oauth`) and Temporal search-attribute registration.
- Use the [Go AI gateway](https://github.com/PostHog/ai-gateway), with credentials for the scout models and the judge model, currently `gpt-6.1-sol` with `xhigh` reasoning effort.
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

Enable the `scout-trials` feature flag for the `project` group with `id = 2`. A missing or unreadable flag blocks new work. Trials also require private capture and the gateway configuration above. The team-2 and staff restrictions still apply even if the flag targets another project. Production MCP also hides rubric and trial tools until the flag is enabled.

Switching the flag off blocks new trials, resumes, queued scout work and new judge dispatch. Judges already dispatched to Tasks can finish, even if their sandbox has not started yet. Saved results remain readable.

Verify the ports and Docker host mapping. Sandbox URLs and MCP's `POSTHOG_API_BASE_URL` must reach services directly, without the Coder login proxy. Keep `POSTHOG_PUBLIC_URL` and `SITE_URL` on the browser URL.
The host-side Tasks worker also uses `SANDBOX_AI_GATEWAY_URL` when minting scoped
tokens. A name such as `host.docker.internal` must resolve from the host as well
as inside Docker; a working container mapping alone is insufficient. Use
`scout_eval_environment ... check --probe` to mint and revoke the private scout
token and ordinary rubric/judge tokens without making a model call. Launch
repeats this check before creating a run. Rubric generation resolves to
`signals_scout_suggestions`; judging resolves to `signals_scout`. Enable both in
`SANDBOX_AI_GATEWAY_PRODUCTS` and configure `SANDBOX_AI_GATEWAY_MINT_KEY`.
Set `SANDBOX_LLM_GATEWAY_URL` explicitly to a local service too: ordinary Tasks
can use this fallback if Go token minting fails, even when the Go URL is local.
The reconstruction check rejects an unset or remote fallback.
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

Suggestion generation captures the complete scout instructions and reference files, attaches them to its sandbox, and uses read-only MCP tools to inspect relevant past runs, reports and live project data. It can read the files in sections instead of relying on shortened prompt excerpts. Past behavior informs suggestions but does not change the scout's assignment. A new scout can receive suggestions without run history, and unavailable evidence is noted in the summary. Generation does not change project data or saved criteria; review and save the suggestions you want.

If an older saved reference is incomplete, generate suggestions again, review and use the new reference, then save. You can keep your existing criteria.
The generator flags unresolved conflicts in the source instructions in its summary instead of choosing a stricter rule. Wording updates to shared defaults affect unsaved rubrics only; saved criteria stay fixed.

Variants and retries share a saved copy of the project's scout memory, notes and recent scout runs. This starting context lives in private object storage and can exceed the 16 MiB limit on launch settings without being shortened.

Each trial scout stores its own memory changes and reports in a separate `trial_state` field on its Signals scout-run record. The small trial marker stays in metadata so ordinary history queries can exclude trials without reading their documents. Tasks run state contains execution settings and token bindings, not trial documents. Signals verifies the sandbox token belongs to that exact run before serving private context. Tasks grants the restricted scout credential only the necessary log, summary and lifecycle writes for its own run; it cannot change another task or steer a trial. Ordinary scout responses omit the private state.

If a trial's scout worker fails or is cancelled, Signals asks Tasks to stop that exact run. Failed runs remain excluded while cleanup proceeds. A failure in the overall comparison does not cancel otherwise healthy scouts.

Trial scouts can use `created_after`, `priority`, `actionability`, and `already_addressed` on `inbox-reports-list`. Report edits, including priority and actionability changes, stay private to the individual run and appear in its subsequent reads; they never modify shared reports or another trial run. Ordering by ranking scores is refused explicitly because private report edits have not been ranked.

Each completed scout run gets its own judge sandbox. The judge reads the saved rubric and searches attached copies of the complete rubric reference, run log, reports, summary, candidate instructions and starting context. These files live in private object storage; Temporal receives only their identifiers. Evidence larger than 128 MiB is refused explicitly instead of being silently shortened.

Signals checks the operator's access, source run and saved evidence before attaching files and dispatching the judge through the existing internal Tasks path used by rubric generation. Queued judges do not repeat Signals-specific staff, skill or source-run checks at sandbox startup. Ordinary account and project permissions still apply when downloading evidence, and Signals checks operator access again before publishing the report.

Judges use ordinary Tasks permissions and logging rather than the scout runs' private credentials and capture suppression. Other sandboxes acting as the same operator in the same project can read judge prompts and attached evidence through the Tasks API.

Scout sandboxes keep private gateway capture and exclude shared context-layer inputs. Tasks no longer calls Signals to interpret trial documents or judge credentials. Shared dispatch preparation, file attachments and budget-stop handling remain unchanged.

The judge has no live project tools, external MCP connections or repository credentials. Its run disables live context, so the Tasks worker neither mounts the current wiki nor adds Store skill descriptions. Internal Tasks also exclude project and personal instructions. Deploy the Tasks worker's support for this run setting before starting new judges.

The judge saves one JSON verdict per rubric check through Tasks' existing structured-output support. Signals checks that same Task until it finishes, then validates its quotes against the original saved files. New evaluations use saved scout identifiers to recheck current permissions on every status poll without downloading the full starting context again; preparation and report finalization still validate that context. Worker restarts resume result collection without starting another judge. If result collection remains unavailable, the evaluation fails without freezing an incomplete report; resuming the same evaluation reuses its Tasks and saved judgments.

The judge first checks whether each criterion applies, including allowed exceptions and optional work. The required skill and project-profile startup reads are distinguished from the investigation itself; incidental metadata in those responses does not by itself prove unrelated investigation. Required step order is checked against the execution timeline; doing both steps in the wrong order does not satisfy it. Unresolved conflicting instructions give an unknown verdict unless another clear violation already fails that criterion. Judge versions cover the model, reasoning effort and prompt. After a version changes, unfinished trials using the older judge require a new trial. Resuming an outdated trial is rejected before more paid runs start. Completed reports stay readable.

Unavailable or ambiguous evidence gives an unknown verdict. A required action proved missing from a complete record fails; missing thoughts alone never prove an omission. Citation checks accept decoded JSON string fields in tool responses. A judge failure is shown separately from a failed rubric check. Each judge has a 30-minute deadline measured from its original Task run creation; retries do not reset it. Up to three collectors run at once, but judge Tasks can briefly overlap beyond that after a delayed start or collection failure. Saved results never rerun the judge when viewed.

Only versions whose runs all completed and were judged can lead. At least two completed versions with the same number of runs are needed; failed versions remain visible and are excluded even if most versions failed. The result compares completed versions by their total confirmed rubric passes. Unknown checks earn no passes and make any leader or tie provisional. Without a confirmed pass, unresolved checks cannot produce a leader. Final winners still require comparable applicable checks. Saved reports retain their original conclusions.

Before dispatch, the full batch must fit the project's existing daily scout budget. Resuming counts only runs that have not already started. This is a capacity check, not a reservation: simultaneous submissions can still race, and the budget remains shared with ordinary scouts.
