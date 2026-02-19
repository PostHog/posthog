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

All in `posthog/api/feature_flag.py` unless noted otherwise.

| Viewset                       | Route                                   | Notes                                                                    |
| ----------------------------- | --------------------------------------- | ------------------------------------------------------------------------ |
| `FeatureFlagViewSet`          | `api/projects/{id}/feature_flags/`      | Primary viewset. Full CRUD, soft delete via `ForbidDestroyModel`.        |
| `LegacyFeatureFlagViewSet`    | `api/feature_flag/`                     | Inherits `FeatureFlagViewSet`, derives team from session.                |
| `OrganizationFeatureFlagView` | `api/organizations/{id}/feature_flags/` | Cross-team operations. File: `posthog/api/organization_feature_flag.py`. |
| `FlagValueViewSet`            | `api/projects/{id}/flag_value/`         | Returns possible values for a flag. File: `posthog/api/flag_value.py`.   |

## Endpoint reference

### CRUD operations

Standard REST on `/api/projects/{id}/feature_flags/`. Hard `DELETE` is blocked — use `PATCH` with `deleted: true` for soft delete.

### Custom actions

| Method | URL                                                     | Description                                                                     |
| ------ | ------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `GET`  | `.../feature_flags/my_flags/`                           | All flags with values for the current user (proxied to Rust service)            |
| `GET`  | `.../feature_flags/local_evaluation/`                   | Flag definitions for local SDK evaluation (ETag support)                        |
| `GET`  | `.../feature_flags/evaluation_reasons/`                 | Evaluate flags for a `distinct_id` with match reasons (proxied to Rust service) |
| `POST` | `.../feature_flags/user_blast_radius/`                  | Estimate how many users a condition affects                                     |
| `POST` | `.../feature_flags/{pk}/create_static_cohort_for_flag/` | Create a static cohort from matched users                                       |
| `GET`  | `.../feature_flags/{pk}/status/`                        | Flag status (ACTIVE, STALE, DELETED, UNKNOWN)                                   |
| `GET`  | `.../feature_flags/{pk}/dependent_flags/`               | Flags that depend on this flag                                                  |
| `POST` | `.../feature_flags/{pk}/dashboard/`                     | Create a usage dashboard for the flag                                           |

### Organization endpoints

| Method | URL                                                 | Description                                     |
| ------ | --------------------------------------------------- | ----------------------------------------------- |
| `GET`  | `/api/organizations/{id}/feature_flags/{key}/`      | Get a flag by key across all accessible teams   |
| `POST` | `/api/organizations/{id}/feature_flags/copy_flags/` | Copy a flag from one project to target projects |

## Key actions in detail

### `local_evaluation`

Returns flag definitions for SDKs that evaluate flags locally (server-side SDKs). Response includes flags (via `MinimalFeatureFlagSerializer`), `group_type_mapping`, and optionally cohort definitions. Supports ETag-based caching. Uses HyperCache with Redis -> S3 -> PostgreSQL fallback.

Requires `ProjectSecretAPIKeyAuthentication` or `TemporaryTokenAuthentication`. Rate limited at 600/minute (overridable per team via `LOCAL_EVAL_RATE_LIMITS`). Checks billing quotas via `list_limited_team_attributes`.

### `my_flags` and `evaluation_reasons`

Both actions **proxy to the Rust flags service** via `get_flags_from_service()` in `posthog/api/services/flags_service.py`. The Rust service URL defaults to `http://localhost:3001` (configured via `FEATURE_FLAGS_SERVICE_URL` in `posthog/settings/data_stores.py`).

### `create_static_cohort_for_flag`

Creates a static cohort containing all users that match a flag's conditions. This is the **only remaining use** of the legacy Python flag matching code in `posthog/models/feature_flag/flag_matching.py`.

## Django model

### FeatureFlag (`posthog/models/feature_flag/feature_flag.py`)

Key things to know:

- `key` is unique per team (`UniqueConstraint(fields=["team", "key"])`)
- Hard deletes are blocked — `deleted` is a soft delete flag
- `version` field provides optimistic concurrency control. Updates use `select_for_update()` and return HTTP 409 on version mismatch.
- `filters` (JSONField) holds conditions, variants, payloads, and aggregation config
- `ensure_experience_continuity` enables hash key overrides for consistent bucketing across identity changes
- `evaluation_runtime` controls whether a flag is evaluated client-side, server-side, or both
- The `@approval_gate` decorator on updates can require approval before changes take effect

**Cache invalidation**: The `refresh_flag_cache_on_updates` signal handler fires on save/delete, calling `set_feature_flags_for_team_in_cache()` via `transaction.on_commit()`.

### Related models (same file)

| Model                        | Purpose                                                                                |
| ---------------------------- | -------------------------------------------------------------------------------------- |
| `FeatureFlagHashKeyOverride` | Experience continuity hash key storage (`managed = False`, handled by Rust migrations) |
| `FeatureFlagDashboards`      | Through table for flag <-> dashboard M2M                                               |
| `FeatureFlagEvaluationTag`   | Links flags to evaluation context tags                                                 |

### Supporting modules

| File                                               | Purpose                                                                    |
| -------------------------------------------------- | -------------------------------------------------------------------------- |
| `posthog/models/feature_flag/flag_matching.py`     | **Legacy** Python evaluation engine (only used for static cohort creation) |
| `posthog/models/feature_flag/flags_cache.py`       | HyperCache for the Rust flags service with signal-based invalidation       |
| `posthog/models/feature_flag/local_evaluation.py`  | Prepares flag data for SDK local evaluation with HyperCache                |
| `posthog/models/feature_flag/user_blast_radius.py` | Estimates user/group match counts for conditions                           |
| `posthog/api/services/flags_service.py`            | HTTP proxy to the Rust flags service                                       |

## Remote config endpoints

Separate from the feature flag viewset, remote config is served by unauthenticated public views. The token in the URL is a public identifier, not a credential.

| URL                        | View                         | Purpose                  |
| -------------------------- | ---------------------------- | ------------------------ |
| `/array/{token}/config`    | `RemoteConfigAPIView`        | JSON remote config       |
| `/array/{token}/config.js` | `RemoteConfigJSAPIView`      | JavaScript remote config |
| `/array/{token}/array.js`  | `RemoteConfigArrayJSAPIView` | Array.js bundle          |

## See also

- [Rust service overview](rust-service-overview.md) - Runtime flag evaluation service
- [Flag evaluation engine](flag-evaluation-engine.md) - How flags are matched and evaluated
- [HyperCache system](hypercache-system.md) - Multi-tier caching for flag definitions
- [Experience continuity](experience-continuity.md) - Hash key overrides design
- [Billing](billing.md) - Quota enforcement for feature flag requests
