---
name: creating-scout-eval-environments
description: >
  Creates isolated scout evaluation devboxes from a saved scout or a draft skill
  and target project. Exports a minimal real-data slice by default, or reconstructs
  from LLM traces when asked. Builds portable Parquet inputs, restores a devbox,
  validates one real Scout trial and leaves the environment running for future
  evaluations. Requires a local PostHog checkout and devbox access.
---

# Creating scout evaluation environments

Start from the user's local machine and deliver a working devbox for future
scout evaluations, together with its reusable private data bundle. Use one shared
restore format for two explicit data routes. A saved scout does not need prior
runs; a draft skill needs a target project and configuration.

Use the repository's [skill writing guide](../writing-skills/SKILL.md) when
changing this workflow. Read the [online trial guide](../../../docs/internal/scout-online-evals-devbox.md)
for local services, routing and trial behavior. Run development commands from the
repository root through `.codex/with-flox`.

## Workflow

1. **Identify the task and source.** Resolve the scout URL/name and project, or
   read the draft skill and its files. Read its actual config, instructions,
   steering, owner notes and dependencies. Use source APIs or MCP for live facts.
   Ask only for information that cannot be discovered. Never edit the source scout
   to make export easier.
2. **Choose the data route.** Default to [a real-data slice](references/real-data.md)
   of the current source project. Use [trace reconstruction](references/traces.md)
   only when requested. Do not silently switch routes or mix generated rows into
   a real-data slice.
3. **Save a private scope plan.** Include the task window, comparisons, linked
   records and required starting state. Preserve complete rows and relationships
   within that scope. Narrow by task needs, not by arbitrary row sampling. Record
   why each dependency is included and what is unsupported.
4. **Export or reconstruct, then pack.** Scripts handle pagination, typed Parquet,
   checksums, stable identities and repeatable writes. Agent judgment chooses the
   scope and, only on the trace route, fills gaps with documented assumptions.
   Attach the scout case with `pack --scout-case` so the result is portable.
5. **Validate before provisioning.** Check bundle structure, references, timezone,
   cutoff, complete pagination and representative task queries. Reject unsupported
   tables, integrations or context before declaring the bundle ready. Routine
   use of this skill does not implement a new adapter or bypass a failed check.
6. **Create a fresh devbox.** Continue through
   [validation and lifecycle](references/validation.md) using
   `hogli devbox:prepare-eval-env`. Provisioning is part of this workflow. Reuse
   existing user authorization and budget; ask only for missing access or a paid
   trial budget when the session does not already provide them.
7. **Validate one real Scout trial.** Check task-relevant queries and local
   routing, then run within the remaining authorized budget and inspect the full
   trace. Fix concrete environment failures. Recreate only a workflow-created
   disposable box when data or shared-state changes require a fresh baseline.
   Scout finding or policy failures are evaluation results, not reasons to
   rewrite its task or skill.
8. **Keep and hand over the working environment.** Leave a successful devbox
   running. Return its project and trial URLs, login route and instructions,
   reusable bundle, restore receipt and validation results.

Stop at bundle preparation only when the user explicitly asks for it or a concrete
host, credential or required-data blocker prevents the remaining work. Preserve
completed outputs, explain the blocker and mark the runtime trial as untested.
A bundle alone does not complete the default workflow.

## Shared rules

- Keep case data, source snapshots, traces, assumptions, bundles, credentials and
  results in an ignored private directory or outside Git. Only reusable code and
  independently invented tests belong in Git. Never mount operator evidence or
  reference answers into the scout sandbox.
- Preserve actual starting memory, prior reports, notes and history. New scouts
  may legitimately have none. Preserve full recorded prompts on the trace route;
  use `prompt_mode="native"` and the ordinary prompt builder for saved/draft
  scouts without recorded replay. Do not add evaluation disclosures to the task.
- Preserve the source timezone. Shift all declared timestamps by one delta at
  first restore. Keep reusable instructions date-neutral where possible and put
  concrete windows in one-time steering. Do not generate future events to hide
  clock advance. A receipt reuses its original cutoff; it does not reset writes.
- Keep normal tools available, including task-forbidden tools, while routing all
  data reads and writes to the isolated instance. No production fallback. Missing
  backing state is a gap, not an empty response to manufacture.
- Score environment fidelity, finding accuracy and scope compliance separately.
  For trace reconstruction, freeze the first version before opening held-out
  exports or expected findings. A scout's silence about synthetic data does not
  prove it believed the environment was production.
- Paid execution uses a shared budget ledger and local Go gateway. Check the
  existing spend authorization, remaining budget and routing before launch. Do
  not ask again for permission already granted. Bundle creation itself makes no
  model calls. Keep external credentials out of the bundle.
- Improve the environment, not the evaluated scout. Keep its task, skill, model
  and scope intact unless the user separately requests changes. Further trial
  comparisons are follow-up work. Default validation uses one inspected trial;
  report its actual coverage before declaring the environment ready.

## Implementation map

- `products/signals/backend/scout_harness/eval_environment/`: source plan/export,
  trace extraction, deterministic event recipes, scout context and trial helpers.
- `products/posthog_ai/eval_harness/environment/`: canonical Parquet, portable
  archive, validation and restore. Its README documents `pack` and `prepare`.
- `products/signals/backend/facade/eval_environment.py`: scout attachment boundary
  used by the generic importer.
