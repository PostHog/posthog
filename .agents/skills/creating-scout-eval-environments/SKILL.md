---
name: creating-scout-eval-environments
description: >
  Creates private, portable Parquet bundles for isolated scout evaluation
  environments from a saved scout or a draft skill and target project. Exports a
  minimal real-data slice by default, or reconstructs from LLM traces when asked.
  Includes supported starting context and uses devbox:prepare-eval-env to restore
  and validate the environment. Requires a PostHog checkout.
---

# Creating scout evaluation environments

Turn a scout's task into the smallest sufficient private data bundle. Use one
shared restore format for two explicit routes. A saved scout does not need prior
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
6. **Create and test a fresh environment when authorized and possible.** Follow
   [validation and lifecycle](references/validation.md): create a new devbox, run
   one real Scout trial, inspect its full trace, and repeat only to fix concrete
   environment failures. Keep a successful devbox running for evaluations.

If execution must stop before provisioning, deliver the validated bundle and
checks that passed, or the concrete dependency preventing a complete bundle.
Clearly mark the runtime trial as untested. Do not call static checks a successful
Scout run.

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
- Paid execution uses a shared budget ledger and local Go gateway. Check spend
  authorization and routing before launch; bundle creation itself makes no model
  calls. Keep external credentials out of the bundle.

## Implementation map

- `products/signals/backend/scout_harness/eval_environment/`: source plan/export,
  trace extraction, deterministic event recipes, scout context and trial helpers.
- `products/posthog_ai/eval_harness/environment/`: canonical Parquet, portable
  archive, validation and restore. Its README documents `pack` and `prepare`.
- `products/signals/backend/facade/eval_environment.py`: scout attachment boundary
  used by the generic importer.
