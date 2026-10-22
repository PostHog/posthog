# Reconstructing from traces

Use this route only when requested. It preserves the recorded starting context and
allows explicitly documented synthesis. For current real source data, use
[the real-data route](real-data.md).

## Establish the evidence boundary

Keep source traces, case data, assumptions, plans, credentials and exports in an
ignored private directory or outside Git. Never mount that directory into the
scout sandbox. Public scripts and this skill describe the workflow only.

Before reconstruction, identify source instructions, the pinned skill and files,
runtime configuration, complete rendered prompt, one-time steering, owner notes,
metadata, and the last observed state before the session made its first write.
Preserve earlier reports, memory and runs. Exclude target-session writes.
Preserve observed organization gates in their real backing rows. In particular,
the importer creates organizations with AI data processing unapproved; an approved
cached profile does not satisfy live write gates. Record defaults for unobserved
organization settings as assumptions.
Match product feature gates needed by captured tools. Use the existing local
`POSTHOG_FEATURE_FLAGS_FORCE_ENABLED` comma-separated list, record it with the
private case, and restart services. A listed tool can still fail its product gate.

Reserve event exports, reference findings, evaluators and validation summaries
for independent checking after the first reconstruction is frozen. Extract only
pre-write reads from raw traces. Tool-call indexes can embed report-write bodies;
filter operations before displaying them.

Treat recorded rows and aggregate results as constraints. Generate missing rows
consistent with those constraints; record choices and unsupported surfaces in a
separate assumptions file. Do not describe generated rows as recovered facts.
Preserve observed list totals, ordering and pagination, not just returned rows.
Check referenced objects too: a link does not establish its target's full content.
Use captured fields where available and declare generated backing context and
unknown fields separately. Keep new context outside the assigned evidence cohort.
Tools forbidden by the task remain available against local data, so violations
can still be observed. Never fall back to production to fill a gap.
Include those tools in the operator's reconstruction preflight, especially member
and identity lookups. Verify their actual responses before launching the scout.
Preserve observed names, emails, logins and team memberships in their real backing
models or local warehouse tables. For missing fields, declare private assumptions
and check for automatically generated identity placeholders in visible responses.
Keep public examples and default addresses on reserved domains; do not fetch
missing identity fields from production.

Compare captured reads of local built-in skills and references with the rendered
files in `products/posthog_ai/dist/skills/`. Record hashes when they match. If they
differ, assemble a private overlay containing only the required skill directories
and set `SANDBOX_LOCAL_SKILLS_HOST_PATH` in the Tasks worker. Never mount raw logs,
assumptions or validation files alongside those skill files.

## Turn observations into a saved recipe

Extract each run mechanically before interpreting its contents. The current
extractor accepts the paginated `log-pages.json` and `logs/` export layout:

```sh
.codex/with-flox python manage.py scout_eval_environment \
  --state-dir /private/workspace extract \
  --run /private/source/run --read-tools /private/source/read-tools.json \
  --output /private/observations/run.json
```

`read-tools.json` is a list of permitted read tool names. Extraction stops at the
first unrecognized operation, conservatively treating it as the write boundary.
Review that boundary before treating the output as complete. Independent runs
can be extracted in parallel into separate files.

Review the extracted observations together when runs share the same starting
state. Match their project, cutoff, skill and context first; keep conflicting
snapshots separate. For each query, connect its filters, grouping and ordering to
the returned facts. Save trace event references for observed fields and counts,
and separate assumptions for fields that the query never exposed. Do not turn
report-writing outputs into reconstruction requirements.

Author the private case and recipe once from those requirements. `EventRecipe`
supports grouped counts, organization frequencies, observed samples and explicit
choices of generated timestamps/properties. Additional state uses the private
adapter described below. Interpreting arbitrary query results and choosing missing
content remains agent work; extraction and rebuilding are scripted.

```sh
.codex/with-flox python manage.py scout_eval_environment \
  --state-dir /private/workspace build-events \
  --recipe /private/case/events.json --output /private/case/events.parquet
```

Before restoring, rebuild to a second temporary file and compare the decoded rows.
The same saved recipe must produce the same rows without further model calls or
trace review. Keep the recipe, source references, assumptions and exact rebuild
commands together in the private handoff. A new restore may shift dates and remap
local identifiers; compare those changes against the restore receipt.

## Prepare and freeze

Build a private case JSON matching `eval_environment/schema.py` and use
`pack --scout-case` to attach supported scout state to the typed Parquet bundle.
The portable flow restores events, governed metrics, and that starting state.
A private adapter outside this format remains a separate dependency; do not
claim that its outputs are portable merely because local seeding succeeded.
The trace helpers in `eval_environment/traces.py` extract reusable observations.
The event recipe supports explicit property omissions on generated rows through
`generated_property_omissions`; it rejects omissions that target observed rows.
Match observed timestamp precision and identifier formats on generated rows.
Explicit timestamps can use deterministic irregular placement while retaining
known bounds, aggregates and support ordering. `generated_uuid_version` defaults
to 5 and also supports 7; v7 clock bits use the source timestamp before restore.
Keep observed rows and identifiers unchanged.

For trace-observed state outside the typed bundle, use a private deterministic
seed-and-check adapter that restores real models and local storage. Complete its
seed step before freezing. Include the event recipe, private builder, assumptions,
supplemental sources and adapter receipt as repeated `freeze --extra-input` paths.
This binds their hashes in both freeze documents along with the restored bundle.
Repeat the same paths if checking an existing freeze; changing an input requires
a new workspace. Keep that baseline immutable once a run starts. Run the adapter's
live-state check before every run or batch; file hashes do not cover database or
object-storage contents.

```sh
.codex/with-flox python manage.py scout_eval_environment \
  --state-dir /private/workspace prepare \
  --case /private/case/case.json --bundle /private/case
.codex/with-flox python manage.py scout_eval_environment \
  --state-dir /private/workspace freeze \
  --case /private/case/case.json --bundle /private/case \
  --extra-input /private/case/events.json \
  --extra-input /private/case/assumptions.json
```

Use a fresh workspace and project for a new baseline. Repeat preparation only
reuses the exact receipt. Do not reinterpret reuse as reset. Keep the first
reconstruction immutable before opening held-out validation material.

The first restore defaults its target cutoff to current UTC, rounded backward to
keep its shift an exact number of seconds. Shift event times,
state timestamps, declared embedded dates and steering windows by that one delta;
retain the project's timezone. Keep reusable skill instructions date-neutral
when they delegate the interval to steering. Supply concrete half-open UTC bounds
in the trial note. Do not synthesize rows after the cutoff to conceal quiet time.
Clock time continues advancing during startup and each session. For date-only or
minute-only query bounds, choose an explicitly aligned `--target-cutoff`; the
default whole-second shift cannot preserve finer changes in those strings.

Trace cases use `prompt_mode="recorded"`. Freeze writes `runtime-prompt.json`
and preserves the recorded full
prompt, including otherwise tempting guidance, and changes only declared ID/time
mappings, live run identity and one-time steering. An absent or changed source fails
closed.

When the user authorizes rewriting the task for ordinary scouting, preserve the
original prompt privately and declare exact `prompt_transformations` in the
case: source text, replacement, reason and expected occurrence count. Freeze binds
those changes too. Rewrite the task skill, its name and steering consistently;
keep its actual scope and detection rules. Remove evaluation disclosures from the
agent-facing instructions without adding claims that the data is real. Keep
isolation in server-side routing, not in instructions asking the scout to act
privately. Check owner notes, metadata, prior reports and tool responses for leftover
labels and inconsistent state. Preserve genuine business context; record every
intentional departure from the trace outside the scout context.
Declare exact internal project URL-prefix replacements for the prepared local
project. Verify its project ID before applying that mapping, and preserve external
links and unrelated source facts.

Restore observed organization and project names through case metadata. Select a
source-backed or neutral local operator with `prepare --user-id` rather than
exposing the importer's evaluation-labelled default account. Record assumptions
for unknown identities separately. Do not rewrite tool failures to hide missing
capabilities: fix the local state or implement the actual supported operation.
Preparation also gives the receipt-bound capture guard a neutral, accurate
event-ingestion label. It preserves the guard's bytecode and frozen receipt;
`check` verifies both behavior and labels.

For this recorded-prompt route, configure backend and relevant workers with:

```dotenv
SCOUT_EVAL_ENVIRONMENT_FILE=/private/workspace/runtime-prompt.json
SCOUT_TRIALS_LOCAL_TEAM_ID=<prepared team id>
```

These switches work only with `DEBUG`; other deployments retain existing trial
eligibility. The recorded-prompt override targets exactly the prepared scout.
Restart workers through the normal stack workflow after changing settings.

During paid runs, set `TEMPORAL_DISABLE_HOT_RELOAD=1` and
`GRANIAN_RELOAD_IGNORE_PATHS=<absolute checkout root>` before starting the worker
and backend. Source edits and formatter cache writes can otherwise restart the
backend mid-request and make working tools return transient failures. Keep
concurrent implementation work out of the evaluated session's runtime.

Continue with [validation and the devbox lifecycle](validation.md).
