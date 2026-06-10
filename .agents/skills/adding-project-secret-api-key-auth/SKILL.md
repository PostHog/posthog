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

## Wiring a viewset action — the checklist

The machinery is shipped but nothing is wired to it yet — the first planned consumer is the endpoints (the product) `run` action. Four things, all required:

### 1. Whitelist the scope/action pair

PSAK-assignable scopes are a global allowlist in `posthog/scopes.py`:

```python
PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION: list[tuple[APIScopeObject, APIScopeActions]] = [("endpoint", "read")]
```

If your product isn't listed, key creation rejects the scope before auth is ever attempted. Add your `(scope_object, action)` tuple here first.

### 2. Add the authenticator and opt in actions

```python
class MyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "endpoint"
    authentication_classes = [ProjectSecretAPIKeyAuthentication]  # extends, TeamAndOrgViewSetMixin keeps session/PAK auth
    psak_allowed_actions = ["run"]
```

`psak_allowed_actions` is **default-deny**: `APIScopePermission` rejects any PSAK request whose action isn't listed ("This action does not support project secret API key access"). List only the programmatic actions — never CRUD that should stay human-driven.

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
- Skip per-object access-control checks for it (PSAK scopes are project-wide by design):

  ```python
  if isinstance(request.user, ProjectSecretAPIKeyUser):
      return  # PSAK bypasses object-level RBAC deliberately
  ```

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

Mirror the PSAK sections of `posthog/api/test/test_authentication.py`, `posthog/test/test_permissions.py`, and `posthog/test/test_rate_limit.py`. Cover at minimum:

- allowed action with correct scope → 200
- action not in `psak_allowed_actions` → 403
- missing/wrong scope → 403
- key from another team's project → 403
- non-PSAK auth on the same action still works
