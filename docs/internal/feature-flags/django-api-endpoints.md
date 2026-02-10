# Django API endpoints

Django serves the admin/management API for feature flags: CRUD operations, local SDK evaluation, analytics, and organization-level operations. Runtime flag evaluation (`/flags`, `/decide`) is routed directly to the [Rust service](rust-service-overview.md) by Contour/Envoy at the Kubernetes infrastructure level -- these requests never reach Django. Django does make internal service-to-service HTTP calls to the Rust service for actions like `my_flags` and `evaluation_reasons`.

The `/api/feature_flag/local_evaluation` endpoint (used by server-side SDKs for local flag evaluation) runs on a **dedicated Django deployment** (`posthog-local-evaluation`), separate from the main Django web service.

## Architecture overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                        Django API                               │
│          (routed via Contour from /api/* paths)                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Project-scoped (CRUD + management)                             │
│  /api/projects/{id}/feature_flags/                              │
│                                                                 │
│  Organization-scoped (cross-team ops)                           │
│  /api/organizations/{id}/feature_flags/                         │
│                                                                 │
│  Legacy (derives team from user session)                        │
│  /api/feature_flag/                                             │
│                                                                 │
│  Flag values                                                    │
│  /api/projects/{id}/flag_value/                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
   ┌──────────┐              ┌──────────────┐
   │ Postgres │              │ Rust flags   │
   │ (CRUD)   │              │ service      │
   │          │              │ (internal    │
   │          │              │  proxy)      │
   └──────────┘              └──────────────┘
```

## Viewsets

### FeatureFlagViewSet

**File**: `posthog/api/feature_flag.py` (line 1341)

The primary viewset for feature flag management. Registered at `api/projects/{project_id}/feature_flags/`.

**Class hierarchy**:

```text
FeatureFlagViewSet
  ├── ApprovalHandlingMixin      (approval workflow for changes)
  ├── TeamAndOrgViewSetMixin     (team/org routing + auth)
  ├── AccessControlViewSetMixin  (RBAC access control)
  ├── TaggedItemViewSetMixin     (tag management)
  ├── ForbidDestroyModel         (prevents hard deletes)
  └── viewsets.ModelViewSet      (full CRUD)
```

**Authentication**: Session, personal API keys, JWT, OAuth, and `TemporaryTokenAuthentication` (for the Toolbar).

**Scope object**: `"feature_flag"` (for API key scoping).

### LegacyFeatureFlagViewSet

**File**: `posthog/api/feature_flag.py` (line 2302)

Inherits `FeatureFlagViewSet` but derives `project_id` from the user's current team. Registered at `api/feature_flag/`.

### OrganizationFeatureFlagView

**File**: `posthog/api/organization_feature_flag.py` (line 22)

Organization-level operations. Registered at `api/organizations/{organization_id}/feature_flags/`.

### FlagValueViewSet

**File**: `posthog/api/flag_value.py` (line 15)

Returns possible values for a flag. Registered at `api/projects/{project_id}/flag_value/`.

## Endpoint reference

### CRUD operations

| Method   | URL                                      | Description                                                    |
| -------- | ---------------------------------------- | -------------------------------------------------------------- |
| `GET`    | `/api/projects/{id}/feature_flags/`      | List flags (supports filters: active, search, type, tags)      |
| `POST`   | `/api/projects/{id}/feature_flags/`      | Create a flag                                                  |
| `GET`    | `/api/projects/{id}/feature_flags/{pk}/` | Get a single flag                                              |
| `PATCH`  | `/api/projects/{id}/feature_flags/{pk}/` | Partial update                                                 |
| `PUT`    | `/api/projects/{id}/feature_flags/{pk}/` | Full update                                                    |
| `DELETE` | `/api/projects/{id}/feature_flags/{pk}/` | **Blocked** (use `PATCH` with `deleted: true` for soft delete) |

### Custom actions

| Method | URL                                                     | Description                                                                     |
| ------ | ------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `GET`  | `.../feature_flags/my_flags/`                           | All flags with values for the current user (proxied to Rust service)            |
| `GET`  | `.../feature_flags/local_evaluation/`                   | Flag definitions for local SDK evaluation (ETag support)                        |
| `GET`  | `.../feature_flags/evaluation_reasons/`                 | Evaluate flags for a `distinct_id` with match reasons (proxied to Rust service) |
| `POST` | `.../feature_flags/user_blast_radius/`                  | Estimate how many users a condition affects                                     |
| `POST` | `.../feature_flags/bulk_keys/`                          | Get flag keys by IDs (batch lookup)                                             |
| `GET`  | `.../feature_flags/activity/`                           | Activity log for all flags                                                      |
| `GET`  | `.../feature_flags/{pk}/activity/`                      | Activity log for a specific flag                                                |
| `GET`  | `.../feature_flags/{pk}/status/`                        | Flag status (ACTIVE, STALE, DELETED, UNKNOWN)                                   |
| `GET`  | `.../feature_flags/{pk}/dependent_flags/`               | Flags that depend on this flag                                                  |
| `POST` | `.../feature_flags/{pk}/dashboard/`                     | Create a usage dashboard for the flag                                           |
| `POST` | `.../feature_flags/{pk}/enrich_usage_dashboard/`        | Add enriched analytics to usage dashboard                                       |
| `POST` | `.../feature_flags/{pk}/create_static_cohort_for_flag/` | Create a static cohort from matched users                                       |
| `GET`  | `.../feature_flags/{pk}/remote_config/`                 | Get decrypted remote config payload                                             |

### Organization endpoints

| Method | URL                                                 | Description                                     |
| ------ | --------------------------------------------------- | ----------------------------------------------- |
| `GET`  | `/api/organizations/{id}/feature_flags/{key}/`      | Get a flag by key across all accessible teams   |
| `POST` | `/api/organizations/{id}/feature_flags/copy_flags/` | Copy a flag from one project to target projects |

### Flag values

| Method | URL                                                   | Description                                     |
| ------ | ----------------------------------------------------- | ----------------------------------------------- |
| `GET`  | `/api/projects/{id}/flag_value/values/?key={flag_id}` | Get possible values (true/false + variant keys) |

## Authentication and rate limiting

### Per-action authentication overrides

| Action             | Authentication                                                      | Permission                        |
| ------------------ | ------------------------------------------------------------------- | --------------------------------- |
| Default            | Session, personal API key, JWT, OAuth, Toolbar token                | Standard team access              |
| `local_evaluation` | `TemporaryTokenAuthentication`, `ProjectSecretAPIKeyAuthentication` | `ProjectSecretAPITokenPermission` |
| `remote_config`    | `TemporaryTokenAuthentication`, `ProjectSecretAPIKeyAuthentication` | `ProjectSecretAPITokenPermission` |

### Rate limiting

| Action             | Throttle class            | Default rate | Per-team overrides                  |
| ------------------ | ------------------------- | ------------ | ----------------------------------- |
| `local_evaluation` | `LocalEvaluationThrottle` | 600/minute   | `LOCAL_EVAL_RATE_LIMITS` setting    |
| `remote_config`    | `RemoteConfigThrottle`    | 600/minute   | `REMOTE_CONFIG_RATE_LIMITS` setting |

### Quota checking

The `local_evaluation` action checks billing quotas:

```python
if getattr(settings, "DECIDE_FEATURE_FLAG_QUOTA_CHECK", True):
    limited = list_limited_team_attributes(QuotaResource.FEATURE_FLAGS, ...)
    if team_id in limited:
        return Response(status=402)  # Payment required
```

## Serializer

### FeatureFlagSerializer

**File**: `posthog/api/feature_flag.py` (line 341)

Key fields:

| Field                          | Type   | Notes                                               |
| ------------------------------ | ------ | --------------------------------------------------- |
| `id`                           | int    | Read-only                                           |
| `key`                          | string | Must match `^[a-zA-Z0-9_-]+$`, unique per project   |
| `name`                         | string | Human-readable description                          |
| `filters`                      | JSON   | Conditions, variants, payloads, aggregation config  |
| `active`                       | bool   | Whether the flag is enabled                         |
| `deleted`                      | bool   | Soft delete marker                                  |
| `ensure_experience_continuity` | bool   | Persist flag values across identity changes         |
| `version`                      | int    | Concurrency control version (incremented on update) |
| `evaluation_runtime`           | string | `"server"`, `"client"`, or `"all"`                  |
| `bucketing_identifier`         | string | `"distinct_id"` or `"device_id"`                    |
| `is_remote_configuration`      | bool   | Remote config flag                                  |
| `has_encrypted_payloads`       | bool   | Whether payloads are encrypted                      |
| `tags`                         | list   | Organizational tags                                 |
| `evaluation_tags`              | list   | Runtime evaluation context tags                     |
| `rollback_conditions`          | JSON   | Rollback trigger conditions                         |
| `experiment_set`               | list   | Associated experiments (read-only)                  |
| `surveys`                      | list   | Associated surveys (read-only)                      |
| `features`                     | list   | Associated early access features (read-only)        |
| `user_access_level`            | string | RBAC access level for current user (read-only)      |

### Concurrency control

Updates use `select_for_update()` with a `version` field:

```python
@approval_gate(["feature_flag.enable", "feature_flag.disable", "feature_flag.update"])
def update(self, instance, validated_data, *args, **kwargs):
    instance = FeatureFlag.objects.select_for_update().get(pk=instance.pk)
    if instance.version != request_version:
        raise Conflict("Flag was modified by another user")
```

Returns HTTP 409 Conflict on version mismatch.

### MinimalFeatureFlagSerializer

A lightweight serializer used for caching and local evaluation responses. Fields: `id`, `team_id`, `name`, `key`, `filters`, `deleted`, `active`, `ensure_experience_continuity`, `has_encrypted_payloads`, `version`, `evaluation_runtime`, `bucketing_identifier`, `evaluation_tags`.

## Key actions in detail

### `local_evaluation`

Returns flag definitions for SDKs that evaluate flags locally (server-side SDKs). The response includes:

- `flags`: List of flag definitions (via `MinimalFeatureFlagSerializer`)
- `group_type_mapping`: Maps group type names to indices
- `cohorts`: Cohort definitions (when `send_cohorts=true`)

Supports ETag-based caching (returns 304 Not Modified when data hasn't changed). Uses HyperCache with Redis -> S3 -> PostgreSQL fallback.

### `my_flags` and `evaluation_reasons`

Both actions **proxy to the Rust flags service** via `get_flags_from_service()`:

```python
# posthog/api/services/flags_service.py
def get_flags_from_service(token, distinct_id, groups=None):
    response = requests.post(
        f"{FEATURE_FLAGS_SERVICE_URL}/flags",
        json={"token": token, "distinct_id": distinct_id, "groups": groups},
    )
    return response.json()
```

The Rust service URL defaults to `http://localhost:3001` (configured via `FEATURE_FLAGS_SERVICE_URL`).

### `user_blast_radius`

Estimates how many users/groups match a condition set. Used in the UI to show the impact of a flag change before saving.

### `create_static_cohort_for_flag`

Creates a static cohort containing all users that match a flag's conditions. This is the **only remaining use** of the legacy Python flag matching code in `posthog/models/feature_flag/flag_matching.py`.

## Django model

### FeatureFlag

**File**: `posthog/models/feature_flag/feature_flag.py` (line 36)

Key fields:

| Column                         | Type            | Notes                            |
| ------------------------------ | --------------- | -------------------------------- |
| `key`                          | CharField(400)  | Unique per team                  |
| `name`                         | TextField       | Description                      |
| `filters`                      | JSONField       | Conditions, variants, payloads   |
| `team`                         | FK to Team      | Owner team                       |
| `deleted`                      | BooleanField    | Soft delete                      |
| `active`                       | BooleanField    | Enabled/disabled                 |
| `version`                      | IntegerField    | Concurrency control              |
| `ensure_experience_continuity` | BooleanField    | Persist flag values              |
| `evaluation_runtime`           | CharField(10)   | `"server"`, `"client"`, `"all"`  |
| `bucketing_identifier`         | CharField(50)   | `"distinct_id"` or `"device_id"` |
| `is_remote_configuration`      | BooleanField    | Remote config flag               |
| `has_encrypted_payloads`       | BooleanField    | Encrypted payloads               |
| `usage_dashboard`              | FK to Dashboard | Associated usage dashboard       |
| `last_called_at`               | DateTimeField   | Last evaluation timestamp        |

**Constraint**: `UniqueConstraint(fields=["team", "key"])`.

**Signal handler**: `refresh_flag_cache_on_updates` fires on save/delete, calling `set_feature_flags_for_team_in_cache()` via `transaction.on_commit()`.

### Related models

| Model                        | File                | Purpose                                                                                |
| ---------------------------- | ------------------- | -------------------------------------------------------------------------------------- |
| `FeatureFlagHashKeyOverride` | Same file, line 516 | Experience continuity hash key storage (`managed = False`, handled by Rust migrations) |
| `FeatureFlagDashboards`      | Same file, line 693 | Through table for flag <-> dashboard M2M                                               |
| `FeatureFlagEvaluationTag`   | Same file, line 708 | Links flags to evaluation context tags                                                 |
| `TeamDefaultEvaluationTag`   | Same file, line 741 | Default evaluation tags for new flags                                                  |

### Supporting modules

| File                                               | Purpose                                                                              |
| -------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `posthog/models/feature_flag/flag_matching.py`     | **Legacy** Python evaluation engine (only used for static cohort creation)           |
| `posthog/models/feature_flag/flag_validation.py`   | Validates flag queries won't timeout                                                 |
| `posthog/models/feature_flag/flag_status.py`       | Determines ACTIVE/STALE/DELETED/UNKNOWN status                                       |
| `posthog/models/feature_flag/flag_analytics.py`    | Redis-based billing analytics for decide/local-eval request counting                 |
| `posthog/models/feature_flag/local_evaluation.py`  | Prepares flag data for SDK local evaluation with HyperCache                          |
| `posthog/models/feature_flag/flags_cache.py`       | HyperCache for the Rust flags service with signal-based invalidation                 |
| `posthog/models/feature_flag/user_blast_radius.py` | Estimates user/group match counts for conditions                                     |
| `posthog/models/feature_flag/types.py`             | TypedDicts: `FlagProperty`, `FilterGroup`, `FlagFilters`, `FlagData`, `FlagResponse` |
| `posthog/api/services/flags_service.py`            | HTTP proxy to the Rust flags service                                                 |

## Approval workflow

The `@approval_gate` decorator on `FeatureFlagSerializer.update()` intercepts flag changes and may require approval before the change takes effect:

```python
@approval_gate(["feature_flag.enable", "feature_flag.disable", "feature_flag.update"])
def update(self, instance, validated_data, *args, **kwargs):
```

Actions gated: enabling, disabling, and updating flags.

## Remote config endpoints

Separate from the feature flag viewset, remote config is served by dedicated views:

| URL                        | View                         | Auth          | Purpose                  |
| -------------------------- | ---------------------------- | ------------- | ------------------------ |
| `/array/{token}/config`    | `RemoteConfigAPIView`        | None (public) | JSON remote config       |
| `/array/{token}/config.js` | `RemoteConfigJSAPIView`      | None (public) | JavaScript remote config |
| `/array/{token}/array.js`  | `RemoteConfigArrayJSAPIView` | None (public) | Array.js bundle          |

These endpoints are unauthenticated. The token in the URL is a public identifier, not a credential.

## Related files

| File                                              | Purpose                                                      |
| ------------------------------------------------- | ------------------------------------------------------------ |
| `posthog/api/feature_flag.py`                     | Main viewset, serializers, throttles                         |
| `posthog/api/organization_feature_flag.py`        | Organization-level viewset                                   |
| `posthog/api/flag_value.py`                       | Flag values viewset                                          |
| `posthog/api/services/flags_service.py`           | Rust flags service proxy                                     |
| `posthog/api/__init__.py`                         | Router registration (lines 162, 251-256, 590-595, 1087-1092) |
| `posthog/models/feature_flag/feature_flag.py`     | Django model and signal handlers                             |
| `posthog/models/feature_flag/local_evaluation.py` | Local evaluation data preparation                            |
| `posthog/settings/data_stores.py`                 | `FEATURE_FLAGS_SERVICE_URL` setting (line 436)               |

## See also

- [Rust service overview](rust-service-overview.md) - Runtime flag evaluation service
- [Flag evaluation engine](flag-evaluation-engine.md) - How flags are matched and evaluated
- [HyperCache system](hypercache-system.md) - Multi-tier caching for flag definitions
- [Experience continuity](experience-continuity.md) - Hash key overrides design
- [Billing](billing.md) - Quota enforcement for feature flag requests
