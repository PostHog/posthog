---
name: adding-activity-logging
description: Adds or changes activity logging (the audit trail) for a Django model in PostHog. Use when a model's writes must show in the Activity side panel or the advanced activity logs, when adding ModelActivityMixin, an ActivityScope, a model_activity_signal receiver, an activity describer, or field exclusions, when auditing which write paths of a model are logged, or when a change is missing from the activity log. Covers the receiver-module convention, writes the signal cannot see (QuerySet.update, bulk_create), the actor outside requests, and product models on a separate database. Trigger terms - activity log, audit log, audit trail, ModelActivityMixin, log_activity, changes_between, activity describer, who changed this.
---

# Adding activity logging

Read [docs/internal/activity-logging.md](../../../docs/internal/activity-logging.md) first.
It carries the pipeline, the file locations, and the reasons.
This skill carries the workflow and the gates.

Reference implementation: `products/feature_flags/backend/activity_logging.py` with its `apps.py`.
Separate-database reference: `products/stamphog/backend/activity_logging.py`.

## Step 1 - Find every write path before you touch the model

The mixin hooks `save()` and `delete()`.
It does not see `QuerySet.update()`, `bulk_create()`, `bulk_update()`, or raw SQL.
A receiver that logs only the API path gives an audit trail that says nobody changed a row a webhook changed.

```sh
rg -n "Thing\.objects|Thing\.all_teams" products/<name>/ --type py | rg -v "tests/"
rg -n "\.update\(|bulk_create\(|bulk_update\(" products/<name>/backend --type py
```

Write the list down: which paths call `save()` (the mixin covers them) and which do bulk writes (you log those by hand in step 5).
Include tasks, Temporal activities, webhook handlers, and management commands.

## Step 2 - Model and scope

- Add `ModelActivityMixin` first in the bases: `class Thing(ModelActivityMixin, TeamScopedRootMixin, ...)`.
- Set `activity_logging_on_delete = True` only when a hard delete must show in the log.
- Add the class name to `ActivityScope` in `posthog/models/activity_logging/activity_log.py`.
- Add the same string to the `ActivityScope` enum in `frontend/src/types.ts`.
- Run `hogli build:openapi` (needs the dev stack) because the API `scope` filter enum is generated from the Literal.

No migration is needed.
The mixin adds no field.

## Step 3 - Receiver module

Create `products/<name>/backend/activity_logging.py`.
One `@mutable_receiver(model_activity_signal, sender=Thing)` per model.
The receiver calls `changes_between` and `log_activity`; nothing else.

Keep the module import-light.
It must not import a viewset, a serializer, or a query runner.
`ready()` imports it at `django.setup()` in every process.

For a model without a `.team` foreign key (`ProductTeamModel`), read `organization_id` from `Team` on the main database inside the receiver.

## Step 4 - Wire it

- In `products/<name>/backend/apps.py` `ready()`: `from products.<name>.backend import activity_logging  # noqa: F401, PLC0415`, with a one-line comment that says why it must connect in every process.
- Add `model_activity:products.<name>.backend.activity_logging.<handler>` to `posthog/test/repo_invariants/setup_receivers_baseline.txt`.

A receiver that is not imported in `ready()` connects only where something else imports the module.
That is the silent failure this convention exists to prevent.

## Step 5 - Bulk writes

For each bulk write from step 1:

- Read the before-values from the writer database before the update.
- Run the update.
- Build one `Change` per field that actually changed, for rows whose value changed.
- Call `bulk_log_activity` (or `log_activity` for one row) with `user=None` when no request user exists, and a `Trigger` that names the job and its id.

Do not wrap a request path in `mute_selected_signals()`.
The flag is process-wide.

## Step 6 - Separate-database products only

When the model is routed in `products/db_routing.yaml`:

- Pass `using=router.db_for_write(Thing)` to every `log_activity` and `bulk_log_activity` call in the product, including the receiver.
  Without it, the audit row is written before the product row commits and survives its rollback.
- The mixin already pins its before-update read to the writer and reads by primary key without a team filter.

## Step 7 - Tune the diff

- Fields a job touches on every run go in `signal_exclusions` (no row is logged when only they change).
- Bookkeeping fields go in `field_exclusions` (dropped from the diff).
- Secrets go in `field_with_masked_contents` (the change is recorded, the values are not).
- User-facing names go in `field_name_overrides`.

## Step 8 - Describer (optional)

`defaultDescriber` renders "X created / updated / deleted <name>".
Write `products/<name>/frontend/activityDescriber.tsx` and register it in `frontend/src/lib/components/ActivityLog/describers.tsx` when the default text does not say what changed in the user's words.
Invoke `/writing-user-facing-copy` before you write the strings.

## Step 9 - Tests

Invoke `/writing-tests` first.
Add the tests listed under Tests in the doc, and no more.

## Verify

```sh
hogli test products/<name>/backend/tests/<file>.py
hogli test posthog/test/repo_invariants/test_startup_import_budget.py
ruff check products/<name>/backend/activity_logging.py posthog/models/activity_logging --fix
```

Then check the row in a shell: `ActivityLog.objects.filter(scope="Thing").order_by("-created_at").first().detail`.

## Debugging a missing row

Work down this list; each item is a distinct cause.

1. The receiver module is not imported in `ready()` (check `setup_receivers_baseline.txt` for the handler name).
2. The write bypassed `save()` (step 1).
3. Only excluded fields changed (`signal_exclusions`), or the diff was empty and `force_save` was not set.
4. `ACTIVITY_LOG_TRANSACTION_MANAGEMENT` deferred the write to a commit that never came, or to the wrong connection (step 6).
5. The row exists but the reader is outside the entitlement's lookback window, or `activity_visibility_restrictions` hides it.
