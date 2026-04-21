# NotificationEvent Architecture — Design Spec

## Goal

Replace the per-recipient `Notification` model with a shared `NotificationEvent` + lazy `NotificationReadState` architecture.
Support targeting users, teams, organizations, and roles with pluggable recipient resolution.
Integrate with the access control system to filter notifications by resource type permissions.

## Context

The current `Notification` model creates one DB row per recipient.
An org-wide notification to 1,000 users creates 1,000 rows + 1,000 Redis publishes.
This design reduces that to one row + one Redis publish regardless of org size.

### Branch structure

The notification feature is split across three stacked PRs managed by Graphite:

| Branch                         | Base                          | PR     | Scope                                      |
| ------------------------------ | ----------------------------- | ------ | ------------------------------------------ |
| `yasen/notifications-models`   | `master`                      | #49311 | Models, migration, enums, product scaffold |
| `yasen/notifications-backend`  | `yasen/notifications-models`  | #49312 | Backend logic, API, Go SSE handler         |
| `yasen/notifications-frontend` | `yasen/notifications-backend` | #49313 | Frontend popover UI                        |

Changes in this spec touch the first two branches.
After implementation, all three branches must be restacked with Graphite (`gt restack`).

---

## Data Model

**Branch: `yasen/notifications-models`**

### NotificationEvent

Replaces the existing `Notification` model (in-place migration — drop and recreate).

| Field               | Type                        | Notes                                                          |
| ------------------- | --------------------------- | -------------------------------------------------------------- |
| `id`                | UUIDField (PK)              | From `UUIDModel`                                               |
| `organization`      | FK Organization             | Always present. Used for channel routing                       |
| `team`              | FK Team, **nullable**       | Present for project-scoped notifications, null for org-level   |
| `notification_type` | CharField                   | From `NotificationType` enum                                   |
| `priority`          | CharField                   | `normal` or `urgent`                                           |
| `title`             | CharField(255)              | Display title                                                  |
| `body`              | TextField                   | Display body, can be blank                                     |
| `resource_type`     | CharField, **nullable**     | From `NotificationResourceType` enum. Used for AC filtering    |
| `resource_id`       | CharField, blank            | Specific resource instance ID                                  |
| `source_url`        | CharField(500), blank       | Deep link URL                                                  |
| `target_type`       | CharField                   | From `TargetType` enum: `user`, `team`, `organization`, `role` |
| `target_id`         | CharField                   | ID of the target entity                                        |
| `resolved_user_ids` | JSONField                   | Snapshot array of user IDs, e.g., `[1, 2, 3]`                  |
| `created_at`        | DateTimeField(auto_now_add) |                                                                |

**Indexes:**

- `(organization, created_at DESC)` — list query
- GIN index on `resolved_user_ids` — containment filter

**Ordering:** `["-created_at"]`

### NotificationReadState

New model. Row exists = read, no row = unread.

| Field                | Type                                    | Notes                   |
| -------------------- | --------------------------------------- | ----------------------- |
| `id`                 | UUIDField (PK)                          | From `UUIDModel`        |
| `notification_event` | FK NotificationEvent, on_delete=CASCADE |                         |
| `user`               | FK User, on_delete=CASCADE              |                         |
| `created_at`         | DateTimeField(auto_now_add)             | When it was marked read |

**Constraints:**

- Unique together: `(notification_event, user)`

**Operations:**

- Mark read → `get_or_create(notification_event=event, user=user)`
- Mark unread → `.filter(notification_event=event, user=user).delete()`
- Mark all read → `bulk_create` rows for events without a read state
- Is unread? → no `NotificationReadState` row exists

### Migration strategy

The PRs have not been deployed. The existing `0001_initial` migration (which creates `Notification`) should be replaced with a new migration that creates `NotificationEvent` and `NotificationReadState`. Locally, the old `notifications_notification` table must be dropped or the migration must handle the transition (e.g., `DeleteModel` + `CreateModel`).

Update the IDOR semgrep rules to reference `NotificationEvent` instead of `Notification`.

---

## Enums

**Branch: `yasen/notifications-models`**

### TargetType (new)

```python
class TargetType(str, Enum):
    USER = "user"
    TEAM = "team"
    ORGANIZATION = "organization"
    ROLE = "role"
```

### NotificationResourceType (new)

Superset of access control resource types plus notification-specific types.
AC filtering is applied only when the resource type has an AC counterpart.

```python
class NotificationResourceType(str, Enum):
    # AC resource types (filtering applied)
    DASHBOARD = "dashboard"
    EXPERIMENT = "experiment"
    FEATURE_FLAG = "feature_flag"
    INSIGHT = "insight"
    NOTEBOOK = "notebook"
    SESSION_RECORDING = "session_recording"
    SURVEY = "survey"
    ERROR_TRACKING = "error_tracking"
    LOGS = "logs"
    # Notification-only types (no AC filtering)
    PIPELINE = "pipeline"
    ALERT = "alert"
    APPROVAL = "approval"
    COMMENT = "comment"
```

### NotificationType (updated)

Keep existing values: `COMMENT_MENTION`, `ALERT_FIRING`, `APPROVAL_REQUESTED`, `APPROVAL_RESOLVED`, `PIPELINE_FAILURE`, `ISSUE_ASSIGNED`.

### Priority (unchanged)

`NORMAL`, `URGENT`.

---

## Recipient Resolution

**Branch: `yasen/notifications-backend`**

### RecipientsResolver

Base class with default implementation that resolves `target_type` + `target_id` to a list of user IDs.

```python
class RecipientsResolver:
    def resolve(self, target_type: TargetType, target_id: str, team_id: int) -> list[int]:
        if target_type == TargetType.USER:
            return [int(target_id)]
        elif target_type == TargetType.TEAM:
            return list(OrganizationMembership.objects.filter(
                organization__teams__id=int(target_id)
            ).values_list("user_id", flat=True))
        elif target_type == TargetType.ORGANIZATION:
            return list(OrganizationMembership.objects.filter(
                organization_id=target_id
            ).values_list("user_id", flat=True))
        elif target_type == TargetType.ROLE:
            return list(RoleMembership.objects.filter(
                role_id=target_id
            ).values_list("user_id", flat=True))
        return []
```

### Custom resolvers

Callers can define their own resolvers for domain-specific recipient logic:

```python
class ApprovalRecipientsResolver(RecipientsResolver):
    def resolve(self, target_type, target_id, team_id):
        policy = ApprovalPolicy.objects.get(id=target_id)
        return [a.id for a in policy.approvers.all()]
```

### Facade contract

```python
@dataclass(frozen=True)
class NotificationData:
    team_id: int
    notification_type: NotificationType
    title: str
    body: str
    target_type: TargetType
    target_id: str
    resource_type: NotificationResourceType | None = None
    resource_id: str = ""
    source_url: str = ""
    priority: Priority = Priority.NORMAL
    resolver: RecipientsResolver | None = None
```

---

## Notification Creation Flow

**Branch: `yasen/notifications-backend`**

`create_notification(data: NotificationData)`:

1. Look up the team to get `organization_id`
2. **Feature flag check** — `posthoganalytics.feature_enabled("real-time-notifications", ...)` at the organization level. If disabled, return None.
3. **Resolve recipients** — `(data.resolver or RecipientsResolver()).resolve(data.target_type, data.target_id, data.team_id)`
4. **Create one `NotificationEvent` row** with `resolved_user_ids` set to the resolved list
5. **On transaction commit** — publish to Redis channel `notifications:{organization_id}`

---

## Redis Pub/Sub

**Branch: `yasen/notifications-backend`**

### Channel structure

- Channel: `notifications:{organization_id}` (one channel per organization)
- No buffer — REST API handles catch-up on reconnect

### Publish payload

```json
{
  "id": "event-uuid",
  "notification_type": "alert_firing",
  "priority": "urgent",
  "title": "...",
  "body": "...",
  "resource_type": "dashboard",
  "resource_id": "",
  "source_url": "/project/3/dashboard/4",
  "resolved_user_ids": [1, 2, 3],
  "created_at": "ISO8601"
}
```

### Fan-out

One publish per notification regardless of org size.
The Go handler filters by user ID before forwarding via SSE.

---

## Go Livestream Handler

**Branch: `yasen/notifications-backend`**

### JWT changes

Add `organization_id` to the JWT claims (same pattern as the existing `user_id` claim added in the original implementation).

### Handler changes

1. Extract `organization_id` and `user_id` from JWT on SSE connect
2. Subscribe to `notifications:{organization_id}`
3. On each message:
   - Parse `resolved_user_ids` from payload
   - Check if connected `user_id` is in the array
   - If yes, forward the event via SSE (strip `resolved_user_ids` from the payload sent to client)
   - If no, skip
4. Heartbeat: 15s
5. Timeout: 30min
6. No buffer replay — removed

### Removed

- Buffer read on connect (`notification_buffer:*` keys)
- Per-user channel subscription

---

## REST API

**Branch: `yasen/notifications-backend`**

Endpoint stays at `/api/environments/{team_id}/notifications/`.
The viewset resolves the organization from the team ID.

### List (`GET /`)

1. Query `NotificationEvent.objects.filter(resolved_user_ids__contains=[request.user.id])` scoped to the team's organization
2. Collect unique non-null `resource_type` values from the result set
3. For each unique resource type that exists in the AC resource list, call `UserAccessControl.check_access_level_for_resource(resource_type, "viewer")` — one query per unique type
4. Build a set of denied resource types
5. Exclude events with a denied `resource_type`
6. LEFT JOIN `NotificationReadState` for `request.user` — annotate `read` (boolean) based on row existence
7. Order by `-created_at`, paginate (max 50)

### Unread count (`GET /unread_count/`)

Same filtering as list, but `COUNT` where no `NotificationReadState` exists.

### Mark read (`POST /{id}/mark_read/`)

`NotificationReadState.objects.get_or_create(notification_event=event, user=request.user)`

### Mark unread (`POST /{id}/mark_unread/`)

`NotificationReadState.objects.filter(notification_event=event, user=request.user).delete()`

### Mark all read (`POST /mark_all_read/`)

Find all `NotificationEvent` IDs for this user that have no `NotificationReadState`.
`NotificationReadState.objects.bulk_create(...)` for those events.

### Serializer

Returns a flat object matching the existing `InAppNotification` frontend type:

```json
{
  "id": "event-uuid",
  "notification_type": "alert_firing",
  "priority": "urgent",
  "title": "...",
  "body": "...",
  "read": false,
  "read_at": null,
  "resource_type": "dashboard",
  "source_url": "/project/3/dashboard/4",
  "created_at": "..."
}
```

`read` is computed from the join (true if `NotificationReadState` row exists, false otherwise).
`read_at` is `NotificationReadState.created_at` if exists, null otherwise.

The frontend does not need to know about the two-table split.

---

## Access Control Integration

**Branch: `yasen/notifications-backend`**

### Filtering strategy

AC filtering happens only in the REST API (not in SSE / Go handler).
The Go handler delivers all notifications where the user is in `resolved_user_ids`.
The badge count from SSE is "optimistic" — corrected when the popover opens and the REST API runs the AC check.

### Optimization

Instead of checking AC per notification, collect unique `resource_type` values from the query result and run one `UserAccessControl.check_access_level_for_resource()` call per unique type. Typical result set has 3-5 unique types → 3-5 AC checks total.

### Non-AC resource types

Notifications with `resource_type` set to a notification-only type (`pipeline`, `alert`, `approval`, `comment`) or `resource_type=NULL` skip AC filtering entirely — all targeted users see them.

### Feature entitlement

AC filtering only applies when the organization has the `ADVANCED_PERMISSIONS` feature. `UserAccessControl.access_controls_supported` returns False without this feature, and `check_access_level_for_resource` returns the default access level (typically `"editor"`), so no notifications would be filtered out for orgs without the entitlement.

---

## Frontend Impact

**Branch: `yasen/notifications-frontend`**

Minimal changes expected:

- The `InAppNotification` TypeScript type shape stays the same (serializer handles flattening)
- The SSE payload shape stays the same (Go handler strips `resolved_user_ids`)
- No frontend model or component changes needed for this spec
- The `sidePanelNotificationsLogic` SSE handler and REST API calls remain unchanged

---

## Branch Change Summary

### `yasen/notifications-models` (PR #49311)

- Replace `Notification` model with `NotificationEvent` + `NotificationReadState`
- Replace migration `0001_initial`
- Add `TargetType` and `NotificationResourceType` enums
- Update facade contracts (`NotificationData`)
- Update IDOR semgrep rules
- Update app registration if model names changed

### `yasen/notifications-backend` (PR #49312)

- Rewrite `create_notification` logic for new model + recipient resolution
- Add `RecipientsResolver` base class and default implementation
- Update `_publish_to_redis` — org-scoped channel, no buffer
- Update REST API viewset — new query patterns, AC filtering, read state joins
- Update serializer — flatten two-table model to same response shape
- Go handler — subscribe to `notifications:{organization_id}`, filter by `user_id in resolved_user_ids`, remove buffer, strip `resolved_user_ids` from SSE payload
- JWT — add `organization_id` claim
- Update tests

### `yasen/notifications-frontend` (PR #49313)

- No changes expected from this spec (serializer maintains same shape)
- Remove `notification_buffer` references in `sidePanelNotificationsLogic` if any

### Graphite restack

After all changes are committed on the respective branches:

```bash
gt checkout yasen/notifications-models
gt restack
gt submit --no-interactive --publish
```

This propagates changes up through the stack: models → backend → frontend.
