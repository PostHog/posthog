# Activity logging

Activity logging is the audit trail of PostHog.
A row in `posthog_activitylog` records who changed what, when, and how.
Users read it in the Activity side panel, on an item's history tab, and on the advanced activity logs page.
Notification destinations and workflows react to it through the `$activity_log_entry_created` internal event.

This doc says how a change becomes an activity row, where the code for a new model goes, and which writes the automatic path cannot see.
The skill `.agents/skills/adding-activity-logging/SKILL.md` carries the step-by-step workflow.
Read this doc before you add or change activity logging.

## How a change becomes an activity row

```text
model.save()
  -> ModelActivityMixin.save()                      posthog/models/activity_logging/model_activity.py
     -> reads the row as it was before the update
     -> model_activity_signal.send(...)             posthog/models/signals.py
        -> receiver in products/<name>/backend/activity_logging.py
           -> changes_between(before, after)        posthog/models/activity_logging/activity_log.py
           -> log_activity(...)
              -> ActivityLog row (main database)
                 -> post_save -> $activity_log_entry_created internal event
```

The actor is not passed down this chain.
`ActivityLoggingMiddleware` (`posthog/middleware.py`) stores the request user and the impersonation flag in a thread-local (`activity_storage`), and the mixin reads them back.
Outside a request the user is `None`, and the row is stored with `is_system=True`.

The receiver is the only part a product writes.
The mixin, the signal, and `log_activity` are core, and they work the same for every model.

## Where the code goes

One receiver module per product, connected at app start.
Seventeen products follow this shape; `products/feature_flags/backend/activity_logging.py` is a complete example in one screen, and `products/stamphog/backend/activity_logging.py` is the separate-database example.

| Piece           | Location                                                                                                                 | Note                                                                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Mixin           | the model class, first in the bases: `class Thing(ModelActivityMixin, TeamScopedRootMixin, ...)`                         | Set `activity_logging_on_delete = True` when a hard delete must show in the log. A soft delete is an update and needs nothing extra.                  |
| Scope           | `ActivityScope` Literal in `posthog/models/activity_logging/activity_log.py`                                             | The scope is the model's class name. The API `scope` filter enum is generated from this Literal, so run `hogli build:openapi` after you add one.      |
| Frontend scope  | `ActivityScope` enum in `frontend/src/types.ts`                                                                          | Same string as the class name.                                                                                                                        |
| Receiver        | `products/<name>/backend/activity_logging.py`                                                                            | `@mutable_receiver(model_activity_signal, sender=Thing)`. Keep the module import-light: no DRF, no viewsets, no query runners.                        |
| Wiring          | `products/<name>/backend/apps.py`, in `ready()`                                                                          | `from products.<name>.backend import activity_logging  # noqa: F401, PLC0415` with a one-line comment that says why it must connect in every process. |
| Receiver budget | `posthog/test/repo_invariants/setup_receivers_baseline.txt`                                                              | The startup import budget lists every receiver connected at `django.setup()`. Add the new one.                                                        |
| Exclusions      | the registries in `activity_log.py`                                                                                      | See "Tune the diff" below.                                                                                                                            |
| Describer       | `products/<name>/frontend/activityDescriber.tsx`, registered in `frontend/src/lib/components/ActivityLog/describers.tsx` | Optional. Without one `defaultDescriber` renders "X created / updated / deleted <name>".                                                              |
| Tests           | `products/<name>/backend/tests/`, or `posthog/test/activity_logging/` for a core model                                   | See "Tests" below.                                                                                                                                    |

### Why the receiver is a separate module

The receiver must connect in every process type: web, Celery, Temporal, management commands.
A model is written from all of them.
If the receiver lives in the viewset module, it connects only where the API loads, and a worker's writes are silently not logged.
The batch exports receiver docstring records that failure.

`ready()` runs at `django.setup()`, so the module it imports must stay light.
A receiver that imports a viewset or a query runner drags that import graph into every process start.
That is also why the model class, not the API module, carries the mixin.

### What the receiver does

```python
@mutable_receiver(model_activity_signal, sender=Thing)
def handle_thing_change(sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs):
    instance = after_update or before_update
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=instance.name,
        ),
    )
```

`activity` is `created`, `updated`, or `deleted`.
A receiver may resolve it further, for example a change of `deleted` from false to true becomes `deleted`, and back becomes `restored` (feature flags do this).

`Detail` carries the display name, the change list, an optional `Trigger` (a job that caused the change), and an optional `context` dataclass that extends `ActivityContextBase` with fields the describer needs (alerts pass the insight id and name).

`log_activity` drops an `updated` row with an empty change list unless `force_save=True`.

### Tune the diff

`changes_between` compares every model field except the ones in `common_field_exclusions` (ids, timestamps, `team`, `created_by`, and similar).
Four registries in `activity_log.py` tune it per scope:

- `signal_exclusions` - skip logging when only these fields changed. Use it for bookkeeping fields a job touches on every run (`last_checked_at`, `next_check_at`).
- `field_exclusions` - drop these fields from the diff but still log the row.
- `field_with_masked_contents` - record that the field changed, never its values. Use it for secrets and encrypted inputs.
- `field_name_overrides` - rename a field in the stored change so the describer shows the user-facing label.

## Writes the signal cannot see

The mixin hooks `save()` and `delete()`.
Everything that bypasses them bypasses the log:

- `QuerySet.update()`
- `bulk_create()` and `bulk_update()`
- raw SQL
- a save inside `mute_selected_signals()`

Before you rely on the mixin, list every write path of the model: `grep` for `.update(`, `bulk_create(`, `bulk_update(`, and `.save(` on that model across the product, including tasks, Temporal activities, and webhook handlers.
For each bulk write, log at the site with `log_activity` or `bulk_log_activity`, build the `Change` objects by hand, and pass a `Trigger` that names the job and its id.
Fetch the values the update will change before you run it, and log a change only for rows whose value actually changes.

`mute_selected_signals()` sets a process-wide flag, not a thread-local one.
Use it only in an offline maintenance job.
In a request path it mutes activity for every other request the process serves at that moment.

## Actor and context outside requests

A Celery task, a Temporal activity, or a webhook handler has no request user.
The row is a system row.
To attribute it to a job, pass a `Trigger(job_type=..., job_id=..., payload=...)` in `Detail`.
A receiver can also read one from `get_current_trigger()` when the job wrapped its write in `ActivityTriggerContext(...)`; the receiver has to read and pass it, the context alone stores nothing.

A model with a fail-closed manager (`TeamScopedRootMixin`, `ProductTeamModel`) raises `TeamScopeError` on any query without team context.
The mixin's before-update read is by primary key without a team filter (`unscoped()`), so a `save()` outside a request works.
Your own reads in the same path still need `with team_scope(team_id):` or `Model.objects.for_team(team_id)`.
See `posthog/models/scoping/README.md`.

## Product models on a separate database

`ActivityLog` lives on the main database.
A product routed to its own database (`products/db_routing.yaml`) writes across two connections, and three things change:

**No `.team` accessor.**
`ProductTeamModel.team_id` is a plain integer, not a foreign key.
The receiver reads `organization_id` from `Team` on the main database:
`Team.objects.filter(id=instance.team_id).values_list("organization_id", flat=True).first()`.

**The audit write must wait for the product database commit.**
`log_activity` defers its insert with `transaction.on_commit` when the connection it watches is inside a transaction.
By default it watches the default connection.
A product write runs inside `transaction.atomic(using=router.db_for_write(Model))`, on another connection, while the default connection is in autocommit.
Without `using`, the audit row is inserted at once and survives a rollback of the product row.
Pass `using=router.db_for_write(Model)` to `log_activity` and `bulk_log_activity`.
A callback registered inside a rolled-back transaction is discarded, so the audit row is dropped with the product row.

**The before-update read is pinned to the writer.**
The mixin reads the previous state by primary key through `router.db_for_write(Model)`, so a lagged reader replica cannot produce a stale diff.
Explicit logging at a bulk-write site should read its before-values from the writer too.

## Reading the log

- `GET /api/projects/:id/activity_log/` - the list the side panel reads.
- `GET /api/projects/:id/advanced_activity_logs/` - filters, field discovery, and export.
- Access control: resource `activity_log`, default level `viewer`.
- Entitlement: the advanced endpoint is gated by `AvailableFeature.AUDIT_LOGS` and applies the entitlement's lookback window (`get_activity_log_lookback_restriction` in `posthog/models/activity_logging/retention.py`). The plain list the side panel reads is not gated the same way. Writes always happen.
- `activity_visibility_restrictions` hides selected rows from non-staff users (login events of impersonated sessions).

A scene that wants its own paginated history registers its URL in `activityLogLogic.tsx`.
Most scenes do not need this; the side panel and deep links work without it.

## Tests

Test the behavior the receiver adds, through a public interface, at the cheapest level:

- One test that a write through the API or the facade creates a row with the expected `activity` and `changes`.
- One test per bulk-write site that its explicit logging produces the expected rows.
- A `changes_between` test only when the scope adds exclusions or masks.
- For a separate-database product, one test that a rolled-back product write leaves no row (`override_settings(ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True)` plus `captureOnCommitCallbacks(using=<writer alias>, execute=True)`).

`ACTIVITY_LOG_TRANSACTION_MANAGEMENT` is off under test, so a plain test sees the row right after the write.
