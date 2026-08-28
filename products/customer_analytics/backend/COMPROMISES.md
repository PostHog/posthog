# Customer analytics — v1 compromises

Shortcuts taken to ship the first version. Revisit when they bite.

## Select custom property option side effects

- **Rename backfill / removal clearing runs inline.** `update_custom_property_definition` rewrites the definition's `CustomPropertyValue` rows synchronously, inside the definition-save transaction (`apply_option_side_effects` in `logic/custom_property_definitions.py`).
  For a definition with many account values this makes the PATCH slow and holds the transaction open.
  Brittle at scale — move to an async backfill job when large value sets bite.
- **Conversion safety lives in a caller-side guard.** Side effects run only while the definition is still `select`: on a select→other conversion the id diff would read every option as removed and wrongly clear all values, which must instead survive as plain strings.
  The guard sits in the facade update path, locked by `test_converting_select_to_text_keeps_values_and_clears_options`; a new write path that skips it would clear values on conversion.

## Custom property view sync

- **Two bulk paths during rollout.** The legacy Celery task still re-queries the live view and has no
  retry. A flagged successful materialization starts an isolated Temporal workflow that reads its
  committed Delta snapshot and writes job-scoped Parquet. Staging failures remain visible without
  failing the materialized view. Source create and re-enable still use Celery until the staged path
  gains manual recovery.
- **Run history is per source and segment.** Each source gets tracked and ignored records before
  staging starts. After both segments finish, their combined outcome updates the source status once.
- **Tracked and ignored segments are independent.** They use separate snapshots, retries, and
  completion markers. Churned accounts are excluded from both. Only staged-file cleanup waits for
  both markers.
- **No save-time column validation.** Creating/updating a source does not check that `source_column`
  / `key_column` exist in the view's schema. A bad column surfaces as a per-source sync error (and
  advances the auto-disable streak) on the next run, not as a 400 on save. Validate against the saved
  query's `columns` at write time if the delayed feedback bites.
- **Initial sync is best-effort.** Saving an enabled source enqueues a sync on commit so values
  populate without waiting for the next materialization. If the broker is down the save still
  succeeds and the enqueue is dropped (logged to error tracking) — the next materialization recovers.
- **Create-path sync is synchronous, best-effort, and workflow-only.** When the external create
  endpoint is called by a workflow "Create account" step (the `X-PostHog-Hog-Flow-Id` header),
  it syncs warehouse-backed custom properties for the new account inline — scoped to its external
  id, materialized views only — so the next workflow step can read the values. Creates without the
  header skip the sync, which keeps the per-request warehouse fan-out off the general create path;
  the header is caller-supplied, so a token holder can opt in by faking it — same trust level as
  the existing workflow attribution. Failures are captured and swallowed: creation never fails,
  and no sync outcome is recorded (streaks and `last_synced_at` belong to the scheduled full
  sync). Values are as fresh as the last materialization. All enabled sources sync, not just
  properties the workflow references — read-side usage isn't indexed, and one filtered query per
  view is cheap. If the added request latency bites, narrow to workflow-referenced properties or
  make the step poll.
- **v2 materialization only.** v1 `run_workflow.py` is frozen and does not dispatch the sync; v1
  teams get it after migrating to v2.

## Account Track Rules schedule

- **The nightly run starts at 06:00 UTC.** Temporal creates the global schedule paused. Operators unpause it after controlled tests and pause it to roll back. Schedule updates preserve the current pause state.
- **The run does not wait for account custom property syncs.** Those syncs follow each saved query's schedule and finish as independent tracked and ignored workflows. A property sync that finishes after 06:00 UTC is applied by the next nightly Track Rules run. A source change can therefore take almost 48 hours to affect account tracking.
- **The first rollout measures this lag instead of coordinating workflows.** Operators can alert on failed runs and enabled teams without a successful run in 36 hours. The 36-hour window starts when rules are enabled, including for teams with no runs. If late property syncs cause meaningful stale account state, trigger one deduplicated Track Rules run after both property-sync segments finish and keep the nightly run as a safety net.

## Account relationships — leftover JSON role keys in stored rows

The relationship tables are the only source of truth for account roles; the JSON role keys
(`csm`, `account_executive`, `account_owner`) are gone from `AccountProperties`.
Stored `Account._properties` rows may still carry them until
`manage.py backfill_account_relationships` has run in the environment
(it assigns any not-yet-migrated JSON holders as relationships, then strips the keys).
Until then `Account.properties` silently ignores unknown stored keys, and the raw keys remain
visible through the HogQL `system.accounts.properties` JSON column.
Delete this section (and the getter's key filter can revert to a plain `model_validate`)
once the command has run everywhere.

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

## Event stream

- **Cascade deletions don't archive the Slack destination.** The managed HogFunction is archived
  in `delete_event_stream` (the facade, the only deliberate deletion path) and in
  `delete_event_streams_for_user` (called from core's `OrganizationMembership` post_delete, so a
  member leaving or being removed from the org stops their stream delivering) rather than a
  `pre_delete` signal on the stream itself, so plain ORM cascades still bypass it. Team deletion
  is harmless — the HogFunction is team-scoped and dies in the same cascade. Hard-deleting an
  owner (`created_by` CASCADE) usually archives via the membership post_delete firing in the same
  collector run, but the ordering isn't guaranteed. Accepted because user hard-deletion is rare
  (members are deactivated or removed from the org, not deleted); if it bites, archive the
  destinations explicitly in the user-deletion flow rather than reintroducing a signal.

## Account custom property changed workflow trigger

- **Volatile synced columns can flood workflows.** A view column that genuinely changes for many
  accounts each sync emits one `$account_custom_property_changed` event — and starts one workflow
  run — per account per sync run. No cap and no emission-volume observability. Acceptable while the
  product is internal-only; before external exposure add emission counts to `SyncResult` and
  guidance to trigger on stable columns.
- **Multi-property triggers fan out.** One event per changed property, so one run per property,
  never one per batch write. The trigger UI warns; routing logic is the workflow author's job.
- **Cross-workflow loops are damped, not prevented.** Same-value writes never emit and frequency
  masking caps rate, but value-flapping loops (workflow A sets X→1, triggering B which sets X→2, …)
  depend on runtime values and cannot be detected statically. The save-time cycle advisory is
  best-effort — static tag/property references only, never a save blocker.
- **Frequency options are account-keyed because account events carry no person.** The generic event
  trigger's frequency options hash on `{person.id}`, which resolves empty on person-less events and
  would mask globally across accounts. CA triggers ship account-keyed options; the generic event
  trigger keeps its person-keyed options and retains this gap for person-less events.
- **current/previous are event properties, not workflow variables.** Same `{event.properties.*}`
  templating access everywhere; auto-populated variables would need executor and trigger-schema
  changes. Revisit only if variable semantics (mutation, Variables taxonomic category) are needed.
  The values land as analytics events in the team's own project (the established pattern —
  conversation events carry old/new status and truncated message content the same way), so they
  are visible to anyone with project access, like the rest of the account's data.
- **No unset/delete emission.** No value-delete path exists; if one is added, its author decides
  whether removal counts as a change.

## Account channel summaries

- **The channel binding is trusted as written.** `slack_channel_id` is an account property any
  account editor can set, and the summary pipeline reads whatever channel it names with the team's
  own SupportHog bot token. An editor can therefore point an account at any channel that team's bot
  is in — including a private channel the editor isn't a member of — and read its summary. Accepted
  for now: editors are internal team members, the token is team-scoped (no cross-team reach), and
  the announcements feature already posts through the same binding. The activity re-resolves the
  binding, cadence, and org AI-processing approval from the DB just before fetching, so stale or
  forged workflow inputs can't widen this. If summaries ever cover channels whose membership matters,
  validate the binding at write time against a server-side channel policy instead.

## Slack workspace URL is hardcoded

- **`SLACK_ARCHIVES_ORIGIN` hardcodes PostHog's own workspace** — in `backend/constants.py` and
  mirrored in `frontend/components/Accounts/accountLinksLogic.ts`. Every Slack link built from it
  (Useful links sidebar, Slack summary message permalinks, channel summary citations) is wrong for
  any team other than us.
  Fine while the product is PostHog-internal; **must be fixed before GA**. The correct value is
  per-team and owned by conversations: the bot's `auth.test` response carries the workspace `url`
  (same call `get_bot_user_id_cached` already caches a field from), so the fix is a cached lookup
  in conversations exposed through its facade, consumed here and by the frontend.

## Tech debt

- **Account property writes have no single choke point.** `Account._properties` is mutated from
  independent paths: `create_account_for_view` / `update_account_for_view` (via the manager)
  and the Max tool's `_create_account` / `_update_account`.
  Anything that must happen on every properties write has to be repeated per call site,
  and a new writer can silently forget it.
  Funneling every properties write through `AccountManager` (and hooking cross-cutting behavior
  there) is the fix if account properties grow more derived behavior.
