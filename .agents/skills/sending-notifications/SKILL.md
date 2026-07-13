---
name: sending-notifications
description: 'How to send real-time in-app notifications from PostHog backend code. Use when integrating notifications into a new feature, wiring up a notification source (alerts, comments, approvals, pipelines, issues), or choosing the right target type and priority for a notification.'
---

# Sending real-time notifications

## When to use this

You're adding notification support to a PostHog feature — for example, notifying a user when they're mentioned in a comment, when an alert fires, or when an approval is requested.

## The facade API

All notification creation goes through a single function. Import from the facade, not from internal modules:

```python
from products.notifications.backend.facade.api import (
    create_notification,
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
)
```

Build a `NotificationData` and call `create_notification`:

```python
event = create_notification(
    NotificationData(
        team_id=team.id,
        notification_type=NotificationType.ALERT_FIRING,
        priority=Priority.CRITICAL,
        title="Event ingestion latency > 30s",
        body="Events are queuing up. Ingestion pipeline is degraded.",
        target_type=TargetType.USER,
        target_id=str(user.id),
        resource_type="dashboard",
        resource_id="42",
        source_url="/dashboard/42",
    )
)
```

Returns a `NotificationEvent` on success, or `None` if the feature flag is disabled, no recipients were resolved, or the scope (team or organization) doesn't exist. Safe to call in any context.

## Scope: team or organization

Every notification needs a scope so the code can look up the organization and check the `real-time-notifications` feature flag. Pass **exactly one** of:

- `team_id` — team scope. Enables per-team recipient access-control filtering (when `resource_type` is access-controlled) and honours each recipient's per-team mute preferences.
- `organization_id` — organization scope, for organization-wide notifications with no single team context. Access-control filtering and per-team mute preferences are **not** applied (there is no team key to gate on).

If both are omitted, `create_notification` logs `notifications.no_target_scope` and returns `None`. Prefer `team_id` whenever a team context exists; reach for `organization_id` only for genuinely org-wide notifications.

Note that scope is distinct from `target_type`/`target_id`, which decide _who_ receives the notification — you can, for example, use a `team_id` scope with an `organization` target.

An organization-scoped notification looks like:

```python
event = create_notification(
    NotificationData(
        organization_id=organization.id,
        notification_type=NotificationType.PROJECT_CREATED,
        title="New project created",
        body="A teammate created a new project in your organization.",
        target_type=TargetType.ORGANIZATION,
        target_id=str(organization.id),
    )
)
```

## NotificationData fields

**Required:**

| Field               | Type               | Description                                                           |
| ------------------- | ------------------ | --------------------------------------------------------------------- |
| `notification_type` | `NotificationType` | Determines the icon in the UI                                         |
| `title`             | `str`              | Notification headline (~100 chars recommended)                        |
| `body`              | `str`              | Longer description shown on expand. Can be empty string               |
| `target_type`       | `TargetType`       | Who receives this: `user`, `team`, `organization`, or `role`          |
| `target_id`         | `str`              | ID of the target (user ID, team ID, org UUID, or role UUID as string) |

Plus **exactly one** scope field — `team_id` or `organization_id` — see [Scope](#scope-team-or-organization) above.

**Optional** (this lists the commonly-used fields, not every field on `NotificationData`):

| Field             | Type                               | Default  | Description                                                                                                                                                                                   |
| ----------------- | ---------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team_id`         | `int \| None`                      | `None`   | Team scope — see [Scope](#scope-team-or-organization). Required unless `organization_id` is set                                                                                               |
| `organization_id` | `UUID \| None`                     | `None`   | Organization scope — see [Scope](#scope-team-or-organization). Required unless `team_id` is set                                                                                               |
| `resource_type`   | `NotificationResourceType \| None` | `None`   | Access-controlled types (e.g. `"dashboard"`) auto-filter recipients without viewer access (team scope only)                                                                                   |
| `resource_id`     | `str`                              | `""`     | ID of the resource for linking                                                                                                                                                                |
| `source_url`      | `str`                              | `""`     | Relative URL path (e.g. `/dashboard/42`), shown as link icon in UI                                                                                                                            |
| `source_type`     | `SourceType \| None`               | `None`   | Originating product surface (e.g. `SourceType.DASHBOARD`), carried through to the delivered event                                                                                             |
| `source_id`       | `str \| None`                      | `None`   | ID of the originating entity; combine with `source_type` for dedup via `has_been_dispatched`                                                                                                  |
| `priority`        | `Priority`                         | `NORMAL` | `normal` = popover only; `critical` = popover + persistent toast                                                                                                                              |
| `archivable`      | `bool`                             | `False`  | Opt in to a per-recipient "archive" (dismiss) action that moves the notification to the recipient's Archived tab. When `False`, recipients can only mark it read/unread (the default pattern) |
| `metadata`        | `dict[str, Any] \| None`           | `None`   | Arbitrary structured data persisted on the event for custom rendering or downstream use                                                                                                       |
| `resolver`        | `RecipientsResolver \| None`       | `None`   | Custom recipient resolver. Default handles user/team/org/role targeting                                                                                                                       |

## Choosing parameters

### Notification type

| Type                 | When to use                                      |
| -------------------- | ------------------------------------------------ |
| `comment_mention`    | User was @mentioned in a comment or discussion   |
| `alert_firing`       | A monitoring alert threshold was breached        |
| `approval_requested` | A change requires the user's approval            |
| `approval_resolved`  | An approval the user requested has been resolved |
| `pipeline_failure`   | A data pipeline or batch export failed           |
| `issue_assigned`     | An error tracking issue was assigned to the user |

### Priority

**Be very careful with `critical`.** It triggers a persistent toast popup that overlays the user's screen and must be manually dismissed. This is intentionally intrusive — reserve it for genuine emergencies like outages, security alerts, or SLA breaches. Overusing `critical` will train users to ignore notifications entirely. When in doubt, use `normal`.

### Target type

| Target         | `target_id` value | Recipients                             |
| -------------- | ----------------- | -------------------------------------- |
| `user`         | User ID           | Just that user                         |
| `team`         | Team ID           | All members of the team's organization |
| `organization` | Organization ID   | All organization members               |
| `role`         | Role ID           | All users with that RBAC role          |

### Resource type and access control

When `resource_type` matches an access-controlled resource (dashboard, feature_flag, experiment, etc.), recipients without `viewer` access are automatically excluded. For notification-only types (`pipeline`, `approval`, `comment`), no AC filtering is applied.

## Delivery pipeline

```text
Django (create_notification)
  → Postgres (NotificationEvent row)
  → Kafka (notification_events topic, on transaction commit)
  → Go livestream service (Kafka consumer)
  → Redis SPUBLISH (sharded pub/sub, keyed by org ID)
  → SSE (/notifications endpoint)
  → Browser (popover + optional toast)
```

Kafka publish happens on `transaction.on_commit` — won't fire if the transaction rolls back.

## Adding a new notification type

1. Add enum value in `products/notifications/backend/facade/enums.py`
2. Add icon mapping in `frontend/src/lib/components/NotificationsMenu/NotificationRow.tsx` (`NOTIFICATION_TYPE_ICONS`)
3. Add the same icon in the toast handler in `frontend/src/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic.tsx` (`iconMap`)
4. Add sample data in `SAMPLE_NOTIFICATIONS` in `products/notifications/backend/presentation/views.py`
5. Run `python manage.py makemigrations notifications`

## Testing

Mock the feature flag in tests:

```python
from unittest.mock import patch

with patch("posthoganalytics.feature_enabled", side_effect=lambda flag, *a, **kw: flag == "real-time-notifications"):
    event = create_notification(data)
```
