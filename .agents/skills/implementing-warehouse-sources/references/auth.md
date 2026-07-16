# Auth: OAuth, credential validation, non-retryable errors, mixins

## OAuth configuration

Before implementing OAuth, **check if the integration already exists** — search `posthog/models/integration.py` loosely for the service name before concluding it's new.

If new:

1. **Env vars**. Add to `posthog/settings/integrations.py`:

   ```python
   YOUR_SOURCE_CLIENT_ID = get_from_env("YOUR_SOURCE_CLIENT_ID", "")
   YOUR_SOURCE_CLIENT_SECRET = get_from_env("YOUR_SOURCE_CLIENT_SECRET", "")
   ```

2. **Integration kind**. In `posthog/models/integration.py`:
   - Add to `IntegrationKind` enum.
   - Add to `OauthIntegration.supported_kinds`.
   - Add an `elif kind == "your-source": return OauthConfig(...)` branch in `oauth_config_for_kind()`.
3. **Redirect URI**: `https://localhost:8010/integrations/your-kind/callback` in the external service.
4. List any new env vars in the final handoff so they can be set in all environments.

## `validate_credentials`

Called with `schema_name=None` at source-create (one cheap probe to confirm the token is genuine) and with `schema_name=<name>` from the per-schema `incremental_fields` action (confirm scope for that specific endpoint).

If the API distinguishes 401 (bad token) from 403 (valid token, missing scope), **accept 403 at source-create** — users may legitimately only grant scopes for the endpoints they want to sync. Re-raise 403 only when `schema_name` is set. Sync-time 403s are handled separately by `get_non_retryable_errors()`.

For per-table scope status in the schema picker, override `get_endpoint_permissions(config, team_id, endpoints) -> {name: None | reason}`: probe each endpoint and return `None` when reachable or a short reason when not. The `database_schema` action surfaces it as each table's `permission_error`, so the user sees which tables need extra scopes and deselects them — it must **never** block source-create. The base default reports everything reachable.

When you do surface a missing scope, name it — providers usually state it (``Required access: `read_x` access scope.``), so parse that into your own message instead of dumping the raw exception or collapsing it to a bare table list. Probe whatever field the **sync query** needs (not just `id`) so the per-table check reflects what syncing that table actually requires. Keep the probe narrow: only a real denial is a missing scope — a throttle, 5xx, or network blip is not, so route those through the retryable path rather than bucketing every exception as "missing permission".

## Non-retryable errors

Override `get_non_retryable_errors()` to mark errors that should permanently fail instead of retrying:

```python
def get_non_retryable_errors(self) -> dict[str, str | None]:
    return {
        "401 Client Error: Unauthorized for url: https://api.example.com": "Your API key is invalid or expired. Please generate a new key and reconnect.",
        "403 Client Error: Forbidden for url: https://api.example.com": "Your API key does not have the required permissions. Please check the key permissions and try again.",
    }
```

Common cases: 401 Unauthorized, 403 Forbidden, invalid/expired tokens, OAuth tokens needing re-auth.

## Mixins

From `products/warehouse_sources/backend/temporal/data_imports/sources/common/mixins.py`:

- `SSHTunnelMixin` — `with_ssh_tunnel()` context plus `make_ssh_tunnel_func()` for deferred tunnel opening.
- `OAuthMixin` — `get_oauth_integration()` to pull `Integration` from the DB.
- `ValidateDatabaseHostMixin` — `is_database_host_valid()` to block internal VPC IPs (unless SSH tunnel is used).
