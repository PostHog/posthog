# Credentials, OAuth, and token scopes

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

## Document required token scopes

If the API issues OAuth scopes or per-resource access tokens, declare every scope the source actually calls so users know what to grant — don't make them grant the full set defensively.

- **OAuth sources:** set `requiredScopes` on `SourceFieldOauthConfig` (space-separated string, matches the OAuth `scope` parameter format). The frontend diffs it against the integration's granted scopes and warns the user with a Reconnect action when any are missing.
- **Non-OAuth sources (PAT, API key):** there's no integration object to inspect, so list scopes in the `caption` instead. Captions render through `LemonMarkdown`, so backticks, bold, and links work.
