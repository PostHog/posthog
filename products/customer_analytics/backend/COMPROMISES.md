# Customer analytics — v1 compromises

Shortcuts taken to ship the first version. Revisit when they bite.

## Select custom property option side effects

- **Rename backfill / removal clearing runs inline.** `update_custom_property_definition` rewrites the definition's `CustomPropertyValue` rows synchronously, inside the definition-save transaction (`apply_option_side_effects` in `logic/custom_property_definitions.py`).
  For a definition with many account values this makes the PATCH slow and holds the transaction open.
  Brittle at scale — move to an async backfill job when large value sets bite.
- **Conversion safety lives in a caller-side guard.** Side effects run only while the definition is still `select`: on a select→other conversion the id diff would read every option as removed and wrongly clear all values, which must instead survive as plain strings.
  The guard sits in the facade update path, locked by `test_converting_select_to_text_keeps_values_and_clears_options`; a new write path that skips it would clear values on conversion.

## Custom property view sync

- **Celery, not Temporal.** The sync runs in a Celery task, not a dedicated Temporal workflow. No
  durable retries and no run-level UI inspection — failures surface via `last_sync_error` on the
  source + error tracking. Move to Temporal if we need durable retries, long-running syncs, or
  per-run inspection.
- **No retries.** A failed run is not retried; it records the failure (advancing the auto-disable
  streak) and waits for the next materialization. Only transient write conflicts retry, in-logic.
- **Direct dispatch by task name, not a signal.** Core (`succeed_materialization_activity`) enqueues
  this product's sync task by name via `send_task`. A generic core signal the product subscribes to
  would keep core ignorant of the consumer, but for a single consumer that isn't worth the wiring (a
  signal definition + a receiver + an app-ready hook). By-name dispatch also keeps the product and
  HogQL out of the data-modeling worker's process, since core imports nothing from here. Trade-off:
  core hardcodes this consumer's task name. If a second consumer ever needs the materialization event,
  switch to a core-owned signal (inversion of control) rather than adding another direct dispatch.
- **No save-time column validation.** Creating/updating a source does not check that `source_column`
  / `key_column` exist in the view's schema. A bad column surfaces as a per-source sync error (and
  advances the auto-disable streak) on the next run, not as a 400 on save. Validate against the saved
  query's `columns` at write time if the delayed feedback bites.
- **Initial sync is best-effort.** Saving an enabled source enqueues a sync on commit so values
  populate without waiting for the next materialization. If the broker is down the save still
  succeeds and the enqueue is dropped (logged to error tracking) — the next materialization recovers.
- **v2 materialization only.** v1 `run_workflow.py` is frozen and does not dispatch the sync; v1
  teams get it after migrating to v2.

## Account relationships — transitional JSON forward-sync

The relationship tables (`AccountRelationshipDefinition` + `AccountRelationship`) exist, but the
legacy JSON role keys (`csm`, `account_executive`, `account_owner`) in `Account._properties` are
still the **source of truth** for account roles. Every JSON role write forward-syncs into the
table via `logic/relationships.sync_from_account_properties` (called from `create_account_for_view`,
`update_account_for_view`, `_apply_external_role_assignments`, and the Max upsert tool), so the
table shadows the JSON and accrues assignment history. Rules while the sync is alive:

- **Nothing may write the relationship table directly** — the next JSON write reconciles direct
  table writes away. That's why the facade deliberately exposes no assign/end functions yet.
- The three seeded definitions are matched **by name** (`SEEDED_DEFINITIONS` maps JSON key →
  definition name). Renaming a seeded definition silently unlinks it from its JSON key.
- Definitions are not auto-created; on teams without them the sync is a silent no-op. They're
  created ad-hoc (or by the future definitions UI).

Cutover checklist — when done, the sync and this section are deleted:

- [ ] Relationship read path in HogQL/query runner replaces the JSON `ExpressionField`s (PR 2)
- [ ] Writers route through `logic/relationships.assign`/`end` instead of JSON keys, facade grows
      assign/end functions (PR 3)
- [ ] Ad-hoc backfill run per environment (create seeded definitions, sync existing accounts)
- [ ] JSON readers migrated (Max context, usage-spike notifications, external API shape, CDP
      "update account" template, Workflows result paths)
- [ ] Delete `sync_from_account_properties` + call sites; strip the three role keys from
      `AccountProperties`

## External account `custom_properties` payload

- **Every definition is emitted, unbounded.** `_to_external_account` includes every team
  custom property definition keyed by name (`null` when unset) so workflow result paths are
  deterministic. The hogflow executor caps all workflow variables at 5 KB of JSON combined and
  the Get account node's default `account` variable stores the whole response body, so a team
  with enough definitions (roughly 100–150 at typical name lengths, fewer with long names or
  populated values) makes every Get account step throw and drop its variables — even in
  workflows that never touch custom properties. If this bites: stop emitting unset definitions
  as `null`, or drop the whole-body default variable in favor of path-scoped ones.
- **Output variable suggestions read one page.** The workflow editor's suggestion chips fetch
  custom property and relationship definitions without pagination (default page size 100), so
  definitions past the first page silently never appear as suggestions — the value still exists
  in the payload and can be mapped by hand. Follow `next` pages in
  `getOutputMappingSuggestions` (workflows frontend registry) if teams that large show up.

## Tech debt

- **Account property writes have no single choke point.** `Account._properties` is mutated from four
  independent paths: `create_account_for_view` / `update_account_for_view` (via the manager),
  `_apply_external_role_assignments` (raw `account.save`, bypassing the manager), and the Max tool's
  `_create_account` / `_update_account`. Anything that must happen on every properties write — like the
  transitional relationship forward-sync — has to be repeated per call site, and a new writer can
  silently forget it. Funneling every properties write through `AccountManager` (and hooking
  cross-cutting behavior there) is the fix if account properties grow more derived behavior; not done
  now because the sync call sites are deleted at relationship cutover anyway.
