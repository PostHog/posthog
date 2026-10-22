# Validate and keep a working environment

This is the default completion of environment creation: provision from the user's
local machine, validate one real Scout trial and keep the working devbox for
future evaluations. Bundle-only output requires an explicit request or a concrete
blocker. Use existing provisioning and spend authorization; do not ask again.
If no paid-run budget is available, ask for that missing limit before launch and
continue the unpaid preparation work.

## Create a fresh devbox

Use the normal devbox credentials and tooling on the user's local machine.
Choose a new, unused devbox name. `devbox:prepare-eval-env` can reuse an existing
named box; that behavior is not a reset. Record the created box's identity and
URL in the private attempt log.

```sh
.codex/with-flox hogli devbox:prepare-eval-env -n <new-devbox-name> \
  --bundle /private/bundle/environment.tar.gz --ref feat/scout-trace-environments
```

Until merge, use `feat/scout-trace-environments` locally and for the devbox.
Record and align their published commit SHAs. Pin `--ref` to the bundle's recorded
commit for a repeatable restore if the branch moves. After merge, use a published
revision containing both the bundle and scout-state support. Uncommitted local
changes do not travel with the data bundle. Follow the existing devbox setup skill
for provisioning and teardown commands; check current help rather than guessing flags.

After import, set `SCOUT_TRIALS_LOCAL_TEAM_ID` to the restored project. For a
`native` case, leave `SCOUT_EVAL_ENVIRONMENT_FILE` unset: the runner builds the
normal prompt from restored state. Its `runtime-prompt.json` is a verification
descriptor, not a runtime override. For `recorded`, point that setting at the
frozen prompt. Apply local service routing from the online trial guide before
running `check --probe`.

If the current host cannot provision devboxes or lacks required credentials,
record the actual limitation and preserve the bundle and completed checks. Do
not turn one host's limitation into the default behavior of this workflow.

## Check the data, routing and spend

Use the online trial guide for Docker, OAuth, Temporal and private gateway setup.
Set MCP's `POSTHOG_API_BASE_URL` explicitly to the local backend. Set sandbox API,
MCP and gateway URLs explicitly to local services. Verify effective worker and
container configuration; a value in a shell does not establish another process's
routing. Keep integration tokens and external MCP connections out of the fixture.
Verify required services with direct health or client checks too: cached or fallback
tool responses can succeed while a dependency is unavailable. Use the normal local
development configuration for Personhog.
Enable both `signals_scout_suggestions` (rubrics) and `signals_scout` (judges) in
`SANDBOX_AI_GATEWAY_PRODUCTS`, with a configured mint key. Set
`SANDBOX_LLM_GATEWAY_URL` explicitly to a local service; ordinary Tasks can fall
back to it if Go token minting fails. Run `check --probe` to mint and revoke each
actual product's token without model calls before starting paid work.

```sh
.codex/with-flox python manage.py scout_eval_environment \
  --state-dir /private/workspace check --case /private/case/case.json --probe
```

The check re-reads local metric fields and event counts/minimum/maximum timestamps
through the existing restore verifier. Compare representative task queries and
useful alternatives against the retained source evidence within its scope.
Event property-level fidelity needs these query checks; aggregate checks cannot
detect every edit. Run supplemental adapters' live checks too. Confirm that the
scout's normal tools read and write only inside the isolated instance, including
tools its task forbids, with no production fallback.

Use one budget ledger across every environment and attempt. Sandbox, judge and
report-validation calls all cost money. Check the remaining authorized budget
before launching. Inspect effective per-product gateway token caps, which override
team/default caps. A new report check mints another token: the ledger's conservative
allowance is not a hard global spending limit. Apply a campaign-wide gateway
wallet/key budget as well. Unknown spend stays reserved until reconciled.

## Run and inspect one trial

Prepare exactly one standalone trial first. Planning makes no model calls:

```sh
.codex/with-flox python manage.py scout_eval_environment \
  --state-dir /private/workspace run --case /private/case/case.json \
  --plan /private/first-plan.json --ledger /private/campaign/budget.json
```

Inspect the plan and its calculated budget allowance. Planning writes no ledger
reservation or model request. If the existing authorization and remaining budget
cover it, add `--launch` to the same command and proceed. Ask for a budget only
when the session does not already provide one, or its remaining amount cannot
cover the launch. Launch reserves the allowance and binds the exact saved plan.
Pending transport retries must preserve that plan, including its launch IDs.
Settled reservations cannot launch again, and legacy pending reservations without
a plan binding must be reconciled from actual usage before creating a new plan.
Poll and export the existing run to inspect it:

```sh
.codex/with-flox python manage.py scout_eval_environment \
  --state-dir /private/workspace export --case /private/case/case.json \
  --plan /private/first-plan.json --output /private/first-result.json
```

Read the full log, including tool responses and available reasoning summaries,
for missing tools, inconsistent counts or metadata, identity mapping errors,
unexpected empty responses, and signs the agent suspects fabricated data or knows
it is being evaluated. Track those two kinds of awareness separately and quote
the actual evidence. Silence does not prove belief in production data. Verify
that the trial used local data and kept its writes isolated.

Score environment fidelity, finding accuracy and scope compliance separately.
A wrong finding or policy violation is an evaluation result when the environment
supplied valid data and tools. Do not improve the task, skill, model or rubric to
make validation pass. Preserve every frozen input and exported result.

## Fix environment failures and retain a working box

Fix concrete environment faults, then repeat the relevant checks and one trial
within the authorized budget. A service or routing repair that leaves the frozen
baseline intact can use the same box. An interrupted trial may use the supported
resume or retry flow; it does not automatically require a reset.

If a repair changes the bundle or shared starting state, save diagnostics and
trial exports first. Delete only the disposable box created for that attempt,
produce a new immutable bundle when needed, and restore into a new box. Never
delete an unrelated or already accepted evaluation environment. An unsupported
required dependency needs a concrete gap report, not invented source data.

Keep a successful devbox running for future evaluations. Return:

- The devbox, project and trial URLs, plus the tested login route and login instructions.
- The bundle path and SHA-256, restore receipt, source cutoff and timezone.
- Trial results, full trace location, validation checks and remaining limitations.

A frozen bundle is repeatable input; it does not prove every possible tool call
works. State what validation actually exercised. If a concrete blocker prevents
a live trial, deliver the partial handoff and explain what remains incomplete.
Reconcile gateway spend, including report validation and judges; missing usage
is not zero.

## Later comparisons

Run repeated sessions or model/prompt comparisons only when requested. A private
JSON list of `TrialVariant` objects passes through `--variants`. Existing Scout
comparisons freeze starting notes/memory/history and use saved rubric judges.
Decide before preparation whether rubric fields will change. On the trace route,
freeze the first reconstruction before inspecting or adopting a reviewed rubric
or its reference outputs. When a rubric will change later, omit `rubrics` and
`updated_at` from `case.config` and keep their source values in private evidence.
Verification compares every included config field before each plan and launch.

Trials keep reports and memory private per run. Keep the underlying project data
stable for the whole batch because queries and pre-existing report reads are live.
Configured local trials share a captured starting project profile. Their
`force_refresh` tool runs the real builder, rolls back shared cache/pruning writes
and background callbacks, and saves its refreshed view in that run's private
state. Other trials continue from the original profile snapshot.
Restore before another batch if anything changed that baseline. Export results
before a full local reset removes their database references. Use a new workspace
after `hogli nuke`/the normal reset flow, then rerun the same preparation workflow.
