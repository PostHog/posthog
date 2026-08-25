# Auto-approve small event-removal deletion requests

## Context

`DataDeletionRequest` (Django admin only, `posthog/admin/admins/data_deletion_request_admin.py`) requires every
request to walk the full `draft → pending → approved` path, with the APPROVED transition gated on ClickHouse Team
membership. Approval exists because ClickHouse deletes are heavyweight mutations that can degrade production query
performance, but a small event-removal request is not heavyweight, and making a human rubber-stamp it is pure latency.

The goal: approve an `event_removal` request automatically when it matches fewer than 100,000 events, always in
`deferred` execution mode (the `adhoc_events_deletion` queue drained by the scheduled `deletes_job`, which is the
low-impact path). Everything else keeps needing a human.

The decision is made by a scheduled Dagster job, not by the submit page. The distinction matters: the job fetches the
ClickHouse stats itself, immediately before deciding, so it approves against a count it measured rather than one an
operator fetched at some unknown earlier time. Deciding at submit time would mean trusting a stale count, which in
turn needs a freshness gate, a compare-and-swap against the stats the page was rendered from, and a token proving the
page actually offered the opt-out. None of that exists when the measurement and the decision are the same step.

The job is the third sweep over this model, alongside `data_deletion_request_pickup_sensor` (polls APPROVED) and
`verify_queued_deletion_requests_job` (sweeps QUEUED).

The model already carries a `requires_approval` BooleanField that nothing reads. This change gives it meaning as the
"do not auto-approve" opt-out.

## Requirements

Every 30 minutes, for each pending request where `request_type == EVENT_REMOVAL` and `requires_approval` is False:

1. Refresh its ClickHouse stats and persist them.
2. Approve it when `end_time` is in the past and `count < 100_000` — an open time range keeps matching newly ingested
   events, so a count taken now can't bound what the deferred drain deletes when it runs later.
3. Otherwise leave it PENDING for the ClickHouse Team, with the reason logged.

Auto-approved requests go `PENDING → APPROVED` with `execution_mode = DEFERRED`, `approved = True`,
`approved_automatically = True`, `approved_at = now`, and `approved_by` left NULL.

## Decisions

- **`requires_approval` is the opt-out**, repurposed rather than adding a field. The submit page is its only writer,
  and it means "a human must approve this": True for non-event-removals (structural — they are never auto-approvable)
  or when the submitter ticks the box, False otherwise. It is removed from the change form so there is exactly one
  control. Time-dependent conditions are deliberately _not_ baked in at submit: the job re-evaluates the time range
  and the count, so a request whose range closes an hour after submission still qualifies later.
- **`approved_by` stays NULL.** No human approved it, so naming one would be a lie the audit trail can't undo.
- **`approved_automatically`** is a new BooleanField carrying that signal instead. It is filterable in the changelist
  and cleared by "revert to draft" alongside the other approval fields.
- **The threshold is a module constant**, not a setting.
- **Only candidates get their stats refreshed**, not every pending request. A pending request sits until a human acts,
  so refreshing all of them would re-run the same (possibly expensive) ClickHouse query every 30 minutes forever, on
  requests the job can't act on anyway.
- **A failure on one request is logged and skipped**, never raised. One request whose HogQL predicate no longer
  compiles must not stop the sweep from approving the others.
- **The schedule defaults to STOPPED**, like every other schedule and sensor in this feature. An operator enables it
  in the Dagster UI; nothing is auto-approved until they do.
- **`submit_view` deliberately keeps no `CLICKHOUSE_TEAM_GROUP` check**, unlike `approve_view` / `retry_view` / the
  verify path. Any staff user can submit a request that the job may then approve without a ClickHouse Team member
  involved, and the cap is per-request rather than per-user. What bounds the blast radius instead is the combination
  of the 100,000-event cap, the closed-time-range requirement (so the count actually bounds what runs), the fact that
  the job measures rather than trusts, deferred-only execution, and the audit trail on the request.

## Implementation

### `posthog/models/data_deletion_request.py`

Already the shared home for this feature's ClickHouse logic (`event_removal_where`, `count_remaining_for_request`,
`verify_queued_request`), used by both the admin and the dag. The stats-fetch chain moved down here from the admin so
the dag doesn't import from a presentation layer, and the sweep logic lives here alongside `verify_queued_request` for
the same reason — the Dagster op is a thin wrapper over it, and the logic is testable without Dagster.

- `refresh_deletion_stats(request)` — fetch and persist. `STATS_FIELDS` is the single list both writers save, so a new
  stat can't reach one path and skip the other. The write is guarded on `updated_at` and raises
  `StaleDeletionRequestError` if the request moved while the count was running: changing the criteria clears the stats
  precisely because the old numbers no longer describe the request, so writing ours back over that edit would
  resurrect a count nobody measured, which a reviewer could then approve against. Both callers already treat a raise
  as "leave it alone and say so".
- `AUTO_APPROVE_MAX_EVENTS = 100_000` and `AUTO_APPROVE_INTERVAL_MINUTES = 30`. The interval lives here rather than
  beside the schedule so the submit page can tell an operator how long their request will sit before it's looked at,
  without the copy and the cron drifting apart.
- `auto_approve_blocker(request) -> str | None` — why this request can't be auto-approved, or None. Ordered:
  not `EVENT_REMOVAL`; `end_time` missing or in the future; `count` is None; `count >= AUTO_APPROVE_MAX_EVENTS`.
  `requires_approval` and `status` are deliberately not checked here — they're a queryset filter and an update guard,
  not properties of the request's size.
- `auto_approve_pending_requests(max_requests, on_event)` — the sweep. Status-guarded update mirroring
  `approve_view`'s pattern, so a concurrent criteria edit (which resets the request to DRAFT and clears its stats)
  can't be approved against a count that no longer describes it.
- `approved_automatically` field; `requires_approval` help text updated.

### Migration

`AddField` of a boolean with a static default (safe, non-blocking) plus a help-text `AlterField` (a SQL no-op).

### `posthog/dags/data_deletion_requests.py`

`auto_approve_pending_deletion_requests_op` → `auto_approve_deletion_requests_job` →
`auto_approve_deletion_requests_schedule` (`*/30 * * * *`, UTC). The op reports approved/skipped/errored counts plus
`max_requests`, so a tick that hit the cap reads as truncated rather than as "that was all of them". No failure hook —
nothing here transitions a request to IN_PROGRESS.

Registered in `posthog/dags/locations/clickhouse.py`.

### `posthog/admin/admins/data_deletion_request_admin.py`

The submit page stops deciding anything. `submit_view` computes
`requires_approval = not auto_approve_candidate or bool(request.POST.get("requires_approval"))` and hands it to
`_submit_for_approval`, which is back to a plain `DRAFT → PENDING` update. `requires_approval` is removed from
`EDITABLE_FIELDS` and the fieldsets (`ModelAdmin.get_form` builds fields from `flatten_fieldsets`, so that is
sufficient); it stays in `list_filter` and in `duplicate_requests`. `approved_automatically` joins `readonly_fields`,
the Audit trail fieldset, and `list_filter`, and is cleared by `revert_to_draft_view`.

### `posthog/templates/admin/posthog/datadeletionrequest/submit.html`

Orange notice when the request is an event removal, explaining that a job will check it within 30 minutes and what
would disqualify it; grey text otherwise naming the request type. The opt-out checkbox renders unchecked, inside the
form, only for event removals.

## Tests

- `posthog/models/test/test_data_deletion_request.py` — parameterized `auto_approve_blocker` (pure function, no DB).
- `posthog/dags/tests/test_data_deletion_requests.py` — the job against the real cluster fixture: approves a small
  pending event removal (NULL `approved_by`, `approved_automatically`, deferred, stats persisted); ignores an
  opted-out request without even measuring it; leaves an oversized one pending but still refreshes its stats; and
  keeps sweeping when one request's predicate won't compile. Plus job/schedule registration, and that the schedule
  actually yields a run on tick — a schedule function that returns nothing is registered and cronned exactly like a
  working one, but Dagster skips every tick and the sweep never runs.
- `posthog/admin/test_data_deletion_request_admin.py` — submit lands in PENDING and records the opt-out; the checkbox
  is offered only to event removals.

## Verification

```bash
hogli test posthog/admin/test_data_deletion_request_admin.py
hogli test posthog/models/test/test_data_deletion_request.py
hogli test posthog/dags/tests/test_data_deletion_requests.py
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py analyze_migration_risk --fail-on-blocked
ruff check posthog --fix && ruff format posthog
```

End-to-end in the local admin (`hogli start`, then `/admin/posthog/datadeletionrequest/`):

1. Create an `event_removal` draft with a closed time range against a small local team. **Review & Submit** → confirm
   the orange notice and the unchecked checkbox, and that it lands in `pending`, not `approved`.
2. Run the job from the Dagster UI (or `auto_approve_deletion_requests_job.execute_in_process()`) → the request flips
   to `approved` / `deferred` with `approved_automatically` set, `approved_by` empty, and fresh `stats_calculated_at`.
3. Repeat with the checkbox ticked → the job leaves it `pending`.
4. Submit a `property_removal` draft → grey text, no checkbox, `pending` with `requires_approval` true, and the job
   ignores it.
5. Confirm `approved_automatically` filters the changelist and that `requires_approval` still does.
