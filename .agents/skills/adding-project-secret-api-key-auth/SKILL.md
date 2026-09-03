---
name: adding-project-secret-api-key-auth
description: 'How to gate a PostHog API endpoint with project secret API key (PSAK) auth — a project-scoped, user-less service credential. Use when adding PSAK support to a viewset action, allowing a new scope for PSAKs, handling synthetic users (ProjectSecretAPIKeyUser), or choosing PSAK-aware rate throttles. Trigger terms: PSAK, ProjectSecretAPIKey, project secret API key, phs_ token, service auth, programmatic endpoint auth.'
---

# Adding project secret API key (PSAK) auth to an endpoint

## What a PSAK is

A `ProjectSecretAPIKey` is a project-scoped, user-less service credential (`posthog/models/project_secret_api_key.py`). It behaves like a personal API key but survives users leaving the project, carries its own scopes, and authenticates as a synthetic user — not a real `User` row.

- Token format: `phs_...` (Bearer header only — no body fallback, unlike the legacy token).
- Scopes are **project-wide within their resource type** and deliberately ignore object-level access controls (per-resource RBAC).
- Do not confuse with `TeamSecretTokenAuthentication` — that validates the legacy per-team `Team.secret_api_token` (also `phs_`-prefixed) and is only for feature-flag local evaluation and similar pre-PSAK surfaces. It is pegged for migrating to PSAK at some point.

Keys are managed at `POST /api/environments/:id/project_secret_api_keys` (label + scopes; plaintext value returned once; `roll` action to rotate; max 50 per project; wildcard `*` scope not allowed).

## Live consumers

Read the closest one before you wire a new action:

| Surface | Scope | Actions |
| --- | --- | --- |
| `products/endpoints/backend/presentation/views/api.py` | `endpoint:read` | `run` |
| `products/experiments/backend/presentation/views.py` | `experiment:read` | `list`, `retrieve` |
| `products/feature_flags/backend/api/feature_flag.py` | `feature_flag:read` | `remote_config` |
| `products/tasks/backend/presentation/views/loops.py` | `loop:write` | `trigger`, `runs` |
| `products/customer_analytics/backend/presentation/views/external.py` | `account:read` | external account list (a function view, so it checks the scope itself) |

The experiments viewset is the reference for a read-only export: it opts standard CRUD reads in, and keeps writes, lifecycle actions, and results on session, personal key, or OAuth auth.

Two more consumers are live but sit outside this checklist, because neither is a DRF viewset.
The Rust feature-flags service accepts `feature_flag:read` keys on the flag-definitions and remote-config paths, for SDK local evaluation.
The Go AI gateway in `PostHog/ai-gateway` accepts `llm_gateway:read` keys, which it reads from a Redis credential projection (`posthog/storage/gateway_credential_cache.py`) instead of Django auth.

## Wiring a viewset action — the checklist

Four things, all required:

### 1. Whitelist the scope/action pair

PSAK-assignable scopes are a global allowlist in `posthog/scopes.py`:

```python
PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION: list[tuple[APIScopeObject, APIScopeActions]] = [
    ("endpoint", "read"),
    ("feature_flag", "read"),
    ("account", "read"),
    ("loop", "write"),
    ("experiment", "read"),
]
```

If your product isn't listed, key creation rejects the scope before auth is ever attempted. Add your `(scope_object, action)` tuple here first, with a comment that says which surface needs it and why a service credential is the right fit. `llm_gateway:read` is deliberately absent: the serializer grants it behind a flag instead.

`feature_flag:read` has a second validator outside Django: the Rust feature-flags service matches that scope string directly in SQL (`rust/feature-flags/src/api/auth.rs`).
If you rename or remove that entry, the Rust query needs the same edit.

### 2. Add the authenticator and opt in actions

```python
class MyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "endpoint"
    authentication_classes = [ProjectSecretAPIKeyAuthentication]  # extends, TeamAndOrgViewSetMixin keeps session/PAK auth
    psak_allowed_actions = ["run"]
```

`psak_allowed_actions` is **default-deny**: `APIScopePermission` rejects any PSAK request whose action isn't listed ("This action does not support project secret API key access"). List only the actions a service credential needs. Read-only CRUD is fine (experiments lists `list` and `retrieve`), but keep writes and lifecycle actions off the list unless the product needs them, as `loop:write` does.

`APIScopePermission` also enforces team binding automatically: a PSAK only works against `view.team == key.team`, so PSAK auth only makes sense on project-scoped (`/api/environments/:id/...`) routes.

### 3. Use PSAK-aware throttles

`PersonalApiKeyRateThrottle` subclasses silently **bypass** PSAK requests (no personal key → no throttling). Use the PSAK-aware pair from `posthog/rate_limit.py`:

- `PersonalOrProjectSecretApiKeyRateThrottle` — per-key budget (keyed `psak:{key_id}`), also still throttles personal keys.
- `ProjectSecretApiKeyTeamRateThrottle` — per-team aggregate (keyed `psak-team:{team_id}`), caps total PSAK load regardless of how many keys a project mints. Stack it alongside the per-key throttle.

Subclass them to set product-specific `scope`/`rate`; remember each throttle keeps its own cache bucket per `scope` string.

### 4. Handle the synthetic user

`request.user` is a `ProjectSecretAPIKeyUser` (a `SyntheticUser`, `posthog/synthetic_user.py`), not a `User`:

- `user.id` is `None` — never use it as a foreign key. Use `user.current_team_id`.
- `has_perm()` always returns `False` — Django permission checks silently deny.
- Shared object-level RBAC already lets service credentials through: `AccessControlPermission` returns early, and `TeamAndOrgViewSetMixin` skips the access-level queryset filter on `list`. PSAK scopes are project-wide by design, so you get that for free.
- Branch only around access-control checks your own product runs (see `loops.py`):

  ```python
  if is_authenticated_via_project_secret_api_key(request):
      return  # PSAK bypasses object-level RBAC deliberately
  ```

  Use `isinstance(user, ProjectSecretAPIKeyUser)` only where no request is in scope.

- `report_user_action` **drops** synthetic users — if you need analytics for PSAK-authenticated calls, capture explicitly with `posthoganalytics.capture(distinct_id=user.distinct_id, ...)` and include an `auth_method` property so both paths emit the same event shape.
- HogQL system tables: `Database.create_for` hides RBAC-scoped system tables the key's scopes don't cover (via `readable_system_table_access_scopes()`).

Helpers in `posthog/permissions.py` when you need to branch: `is_authenticated_via_project_secret_api_key(request)` and `is_service_auth(request)` (covers PSAK + legacy team token).

## What you get for free

- **Query tagging**: the authenticator calls `tag_authentication(access_method=AccessMethod.PROJECT_SECRET_API_KEY, api_key_mask=..., api_key_label=...)`, so ClickHouse `query_log` attribution works with no per-endpoint code. If you add a new authenticator, tag through `tag_authentication` (the single funnel in `posthog/clickhouse/query_tagging.py`) — not with ad-hoc `tag_queries` calls.
- **`last_used_at` tracking**: updated at most hourly via `.update()` (bypasses `ModelActivityMixin` so routine auth doesn't spam the activity log).
- **Activity logging** on key create/update/roll/delete.

## Calling a PSAK-gated endpoint

```bash
curl -s https://us.posthog.com/api/environments/<project_id>/<your_action_path>/ \
  -H "Authorization: Bearer phs_<key>" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

## Testing

Mirror the PSAK sections of `posthog/api/test/test_authentication.py`, `posthog/test/test_permissions.py`, and `posthog/test/test_rate_limit.py`. `products/experiments/backend/test/test_experiment_psak_auth.py` is a compact per-product example. Cover at minimum:

- allowed action with correct scope → 200
- action not in `psak_allowed_actions` → 403
- missing/wrong scope → 403
- key from another team's project → 403
- non-PSAK auth on the same action still works
