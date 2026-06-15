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

Returns a `NotificationEvent` on success, or `None` if the feature flag is disabled, no recipients were resolved, or the team doesn't exist. Safe to call in any context.

## NotificationData fields

**Required:**

| Field               | Type               | Description                                                                |
| ------------------- | ------------------ | -------------------------------------------------------------------------- |
| `team_id`           | `int`              | Team context — used to look up the organization and check the feature flag |
| `notification_type` | `NotificationType` | Determines the icon in the UI                                              |
| `title`             | `str`              | Notification headline (~100 chars recommended)                             |
| `body`              | `str`              | Longer description shown on expand. Can be empty string                    |
| `target_type`       | `TargetType`       | Who receives this: `user`, `team`, `organization`, or `role`               |
| `target_id`         | `str`              | ID of the target (user ID, team ID, org UUID, or role UUID as string)      |

**Optional:**

| Field           | Type                               | Default  | Description                                                                               |
| --------------- | ---------------------------------- | -------- | ----------------------------------------------------------------------------------------- |
| `resource_type` | `NotificationResourceType \| None` | `None`   | Access-controlled types (e.g. `"dashboard"`) auto-filter recipients without viewer access |
| `resource_id`   | `str`                              | `""`     | ID of the resource for linking                                                            |
| `source_url`    | `str`                              | `""`     | Relative URL path (e.g. `/dashboard/42`), shown as link icon in UI                        |
| `priority`      | `Priority`                         | `NORMAL` | `normal` = popover only; `critical` = popover + persistent toast                          |
| `resolver`      | `RecipientsResolver \| None`       | `None`   | Custom recipient resolver. Default handles user/team/org/role targeting                   |

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
