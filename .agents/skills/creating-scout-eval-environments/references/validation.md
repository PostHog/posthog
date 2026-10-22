# Validate and keep a working environment

## Check routing and spend

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
  --state-dir /private/workspace check --case /private/case/case.json
```

The check re-reads local metric fields and event counts/minimum/maximum timestamps
through the existing restore verifier. Event property-level fidelity still needs
independent task-relevant query checks; aggregate checks cannot detect every edit.
Run supplemental adapters' live checks too.

Use one budget ledger across every environment and attempt. Sandbox, judge and
report-validation calls all cost money. Inspect effective per-product gateway
token caps, which override team/default caps. A new report check mints another
token: the ledger's conservative allowance is not a hard global spending limit.
Apply a campaign-wide gateway wallet/key budget as well. Unknown spend stays
reserved until reconciled.

## Prove one session before comparing variants

Prepare exactly one standalone trial first. Planning makes no model calls:

```sh
.codex/with-flox python manage.py scout_eval_environment \
  --state-dir /private/workspace run --case /private/case/case.json \
  --plan /private/first-plan.json --ledger /private/campaign/budget.json
```

Inspect the plan and its calculated budget allowance. Planning writes no ledger
reservation or model request. Add `--launch` to the same command only when execution
is authorized; launch reserves the allowance and binds the exact saved plan.
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
it is being evaluated. Track those two kinds of awareness separately and quote the
actual evidence. Silence does not prove belief in production data. Distinguish a
bad reconstruction from a valid scout policy violation. Fix concrete environment
problems, create a fresh devbox from the revised bundle, then inspect another single run
before repeating a batch. Keep every earlier frozen input and exported result.

Only after the setup works, run repeated sessions or provide a private JSON list
of `TrialVariant` objects through `--variants`. Existing Scout comparisons freeze
starting notes/memory/history and run the saved rubric judges. Adopt or save the
reviewed rubric after reconstruction is frozen, using the existing rubric tools.
Decide this before preparation: rubric generation and saving change the config's
`rubrics` and `updated_at`, and verification compares every `case.config` field
before each plan and launch. When rubrics will change later, omit both fields from
`case.config` and keep their source values in private evidence.
Keep finding accuracy, scope compliance and reconstruction fidelity separate.

Trials keep reports and memory private per run. Keep the underlying project data
stable for the whole batch because queries and pre-existing report reads are live.
Configured local trials share a captured starting project profile. Their
`force_refresh` tool runs the real builder, rolls back shared cache/pruning writes
and background callbacks, and saves its refreshed view in that run's private
state. Other trials continue from the original profile snapshot.
Restore before another batch if anything changed that baseline. Export results
before a full local reset removes their database references. Use a new workspace
after `hogli nuke`/the normal reset flow, then rerun the same preparation workflow.

## Devbox lifecycle

Run provisioning from a host with the normal devbox credentials and tooling.
Do not try to provision a devbox from inside a devbox when that host cannot do it.
If the user limits work to bundle preparation, stop before this step and report
that runtime validation remains outstanding.

Choose a new, unused devbox name for each attempt. `devbox:prepare-eval-env` can
reuse an existing named box; that behavior is not a reset. Record the created
box's identity and URL in the private attempt log.

```sh
.codex/with-flox hogli devbox:prepare-eval-env -n <new-devbox-name> \
  --bundle /private/bundle/environment.tar.gz
```

Before the importer changes are merged, use `--ref` with the published revision
containing both the bundle and scout-state support. Uncommitted local changes do
not travel with the data bundle. Follow the existing devbox setup skill for
provisioning and teardown commands; check their current help rather than guessing
flags.

After import, set `SCOUT_TRIALS_LOCAL_TEAM_ID` to the restored project. For a
`native` case, leave `SCOUT_EVAL_ENVIRONMENT_FILE` unset: the runner builds the
normal prompt from restored state. Its `runtime-prompt.json` is a verification
descriptor, not a runtime override. For `recorded`, point that setting at the
frozen prompt. Apply local service routing from the online trial guide before
running `check --probe`.

If an attempt fails, save its diagnostics and any trial exports, then delete only
the devbox created for that attempt. Fix supported export or bundle problems,
produce a new immutable version, and try a new box. An unsupported dependency is
a stop with a concrete gap report, not a reason to invent source data.

Keep a successful devbox running. Return its project and trial URLs, bundle path
and SHA-256, source cutoff and timezone, validation report, and unresolved limits.
A frozen bundle is repeatable input; it is not proof that every possible tool call
works. Record what the validation actually exercised.

Reconcile completed gateway spend before another paid batch. Include report
validation and judges; missing usage is not zero.
