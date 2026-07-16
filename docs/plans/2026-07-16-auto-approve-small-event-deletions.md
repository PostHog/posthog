# Auto-approve small event-removal deletion requests

## Context

`DataDeletionRequest` (Django admin only, `posthog/admin/admins/data_deletion_request_admin.py`) currently
requires every request to walk the full `draft → pending → approved` path, with the APPROVED transition gated
on ClickHouse Team membership. Approval exists because ClickHouse deletes are heavyweight mutations that can
degrade production query performance, but a small event-removal request is not heavyweight, and making a human
rubber-stamp it is pure latency.

The goal: when an `event_removal` request has fresh stats showing fewer than 100,000 matching events, approve it
automatically at submit time, always in `deferred` execution mode (the `adhoc_events_deletion` queue drained by
the scheduled `deletes_job`, which is the low-impact path). Everything else keeps needing a human.

The model already carries a `requires_approval` BooleanField that nothing reads. This change gives it meaning as
the "do not auto-approve" opt-out.

## Requirements

Auto-approve on submit when **all** hold:

1. `request_type == RequestType.EVENT_REMOVAL`
2. `end_time` is in the past — an open range keeps matching new events, so a count taken now can't
   bound what the deferred job deletes when it drains later
3. `stats_calculated_at` is set and within 24 hours
4. `count` is not None and `< 100_000`
5. The submit page actually offered the opt-out (posted `auto_approve_offered`), so a page rendered
   while the request was ineligible can't auto-approve after a concurrent stats fetch makes it eligible
6. The submitter did not tick "do not auto-approve"

Auto-approved requests go straight `DRAFT → APPROVED` with `execution_mode = DEFERRED`, `approved = True`,
`approved_by = <the submitting user>`, `approved_at = now`. Anything failing a condition submits to `PENDING` as
it does today.

The submit page shows an orange notice when the request will auto-approve (stating why), and grey explanatory
text when it will not (stating which condition failed).

## Decisions

- **`requires_approval` is the opt-out**, repurposed rather than adding a field. The submit page becomes its only
  writer, and the field means "a human must approve this": anything reaching PENDING writes `True` (whether the
  submitter opted out or the gate blocked it), and only auto-approval writes `False`. Writing the raw checkbox
  value instead would leave blocked requests at `False` and hide them from the changelist's "requires approval"
  filter. It is removed from the change form so there is exactly one control.
- **`approved_by` = the submitting user.** The admin log entry records that the approval was automatic.
- **Stats must be < 24h old**; stale stats fall back to manual with grey text saying to refresh.
- **Threshold is a module constant**, not a setting.
- **`submit_view` deliberately keeps no `CLICKHOUSE_TEAM_GROUP` check**, unlike `approve_view` / `retry_view` / the
  verify path. Auto-approval means the submitter approves, so requiring the group here would remove the entire
  latency win. The consequence, accepted knowingly: any staff user can queue a sub-100k deletion without a
  ClickHouse Team member involved, and the cap is per-request rather than per-user. What bounds the blast radius
  instead is the combination of the 100,000-event cap, the closed-time-range and stats-freshness requirements
  (so the count actually bounds what runs), deferred-only execution, and an audit-logged `approved_by`.

## Implementation

### 1. `posthog/models/data_deletion_request.py`

Update the `requires_approval` help text to describe its new meaning (blocks auto-approval of small event-removal
requests; set from the submit page). No other model change.

### 2. Migration

`help_text` changes are schema-state-only, so this is a plain `AlterField` on `requires_approval`. Generate with
`makemigrations`, no data migration, no default change. Existing rows keep `requires_approval=True`, i.e. they
stay on the manual path until resubmitted, which is the safe direction.

### 3. `posthog/admin/admins/data_deletion_request_admin.py`

Add near `CLICKHOUSE_TEAM_GROUP`:

```python
AUTO_APPROVE_MAX_EVENTS = 100_000
AUTO_APPROVE_MAX_STATS_AGE = timedelta(hours=24)
```

Add an eligibility helper that returns the reason it is _not_ eligible (or `None` when it is), so the view and the
template share one source of truth:

```python
def auto_approval_blocker(obj: DataDeletionRequest) -> str | None:
    """Why this request can't be auto-approved on submit, or None when it can."""
```

Ordered checks, each returning the grey-text sentence rendered on the submit page:

- not `EVENT_REMOVAL` → only event removal requests can be auto-approved
- `stats_calculated_at` is None → no stats fetched yet
- stats older than `AUTO_APPROVE_MAX_STATS_AGE` → stats are stale, refresh them
- `count` is None or `>= AUTO_APPROVE_MAX_EVENTS` → at or above the 100,000 limit

The `requires_approval` opt-out is deliberately **not** part of this helper. It is the operator's choice, not a
property of the request, so the submit page can show the eligibility notice regardless of the checkbox state.

**Remove `requires_approval`** from `EDITABLE_FIELDS` and from the first fieldset. `ModelAdmin.get_form` builds
fields from `flatten_fieldsets`, so dropping it from `fieldsets` is sufficient to keep it off the change form; the
custom `DataDeletionRequestForm.Meta.exclude` needs no change. Leave it in `list_filter` (now meaningful) and in
`duplicate_requests` (a copy inherits the original's choice).

**`submit_view`** — extend the existing flow, keeping its current structure:

- GET: add `auto_approval_blocker` and `will_auto_approve` (blocker is None) to the template context.
- POST: after the existing `missing_*` guards, read `requires_approval = bool(request.POST.get("requires_approval"))`
  (the checkbox posts only when ticked). Compute the blocker server-side, never trust a posted eligibility flag.
  - Auto-approve path (`not requires_approval and blocker is None`): a single status-guarded update, mirroring
    `approve_view`'s pattern:

    ```python
    updated = DataDeletionRequest.objects.filter(pk=obj.pk, status=RequestStatus.DRAFT).update(
        status=RequestStatus.APPROVED,
        requires_approval=False,
        approved=True,
        approved_by=request.user,
        approved_at=timezone.now(),
        execution_mode=ExecutionMode.DEFERRED,
        updated_at=timezone.now(),
    )
    ```

    Then `log_change(...)` recording the automatic approval, and a success message saying it was auto-approved and
    queued for the scheduled deletes job.

  - Manual path: today's `DRAFT → PENDING` update, plus `requires_approval=requires_approval` so the operator's
    choice is persisted.

  Both paths keep the existing "Request is no longer in draft status." fallback when `updated` is 0.

No sensor change is needed: `data_deletion_requests.py` already polls for `status=RequestStatus.APPROVED` and
honors `execution_mode`, so an auto-approved request is picked up exactly like a hand-approved one.

### 4. `posthog/templates/admin/posthog/datadeletionrequest/submit.html`

- Replace the read-only `Requires approval` row with a checkbox inside the existing `<form>`, rendered unchecked,
  only when `will_auto_approve` (there is nothing to opt out of otherwise).
- When `will_auto_approve`, an orange notice above the form (matching the inline-style convention of the red
  `missing_*` blocks: `border: 1px solid #f0ad4e; background: #fcf8e3; color: #8a6d3b`) explaining that the
  request will be approved and queued automatically, why, and that it runs in deferred mode.
- When not, grey text (`color: #666`) rendering the blocker and noting the request goes to pending for ClickHouse
  Team review.

## Tests

`posthog/admin/test_data_deletion_request_admin.py`, extending the existing submit-view test class with
`parameterized` per repo convention:

- Parameterized `auto_approval_blocker` cases: eligible; property_removal; person_removal; no stats; 25h-old
  stats; count at exactly 100,000; count above it; count None.
- Submit POST, eligible, box unticked → `APPROVED`, `approved`, `approved_by == user`, `DEFERRED`,
  `requires_approval is False`.
- Submit POST, eligible, `requires_approval=on` → `PENDING`, not approved, `requires_approval is True`.
- Submit POST, ineligible (count 200,000), box unticked → `PENDING`, not approved. Proves eligibility is
  recomputed server-side rather than taken from the form.
- Submit GET exposes `will_auto_approve` / `auto_approval_blocker` in the context.

## Verification

```bash
hogli test posthog/admin/test_data_deletion_request_admin.py
hogli test posthog/models/test/test_data_deletion_request.py
ruff check posthog/admin posthog/models --fix && ruff format posthog/admin posthog/models
```

End-to-end in the local admin (`hogli start`, then `/admin/posthog/datadeletionrequest/`):

1. Create an `event_removal` draft, click **Fetch stats** on the change page against a small local team so `count`
   lands under 100,000.
2. **Review & Submit** → confirm the orange notice and the unchecked opt-out checkbox appear. Submit → the request
   lands in `approved` / `deferred` with you as `approved_by`, and the admin log line records the auto-approval.
3. Repeat with the checkbox ticked → lands in `pending` with `requires_approval` true.
4. Create a `property_removal` draft and a stats-free `event_removal` draft → both show grey text naming the
   specific blocker, no checkbox, and submit to `pending`.
5. Confirm `requires_approval` no longer renders on the change form and still filters the changelist.
