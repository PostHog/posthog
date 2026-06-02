# Custom REST source

A user-defined data-warehouse source. The user supplies a JSON **manifest** in the same
`RESTAPIConfig` shape that powers the built-in REST sources (Attio, Chargebee, Clerk, …), so the
shared REST engine in [`../common/rest_source/`](../common/rest_source/) handles pagination, auth,
JSONPath extraction, and incremental params with no per-source code.

The source is alpha and gated to a single pilot team on PostHog Cloud US
(`is_custom_source_available_for_team`) plus the `dwh_custom_source` feature flag, until SSRF
protection for arbitrary user-supplied URLs is fully enabled.

## Manifest shape

```jsonc
{
  "client": {
    "base_url": "https://api.example.com/v1/",
    "auth": {
      /* see Auth below */
    },
    "headers": { "Accept": "application/json" }, // optional, non-secret
  },
  "resources": [
    {
      "name": "orders",
      "primary_key": "id",
      "sort_mode": "asc", // "asc" (default) | "desc"
      "endpoint": {
        "path": "orders",
        "method": "GET", // GET | POST only
        "data_selector": "data", // JSONPath to the row array
        "incremental": { "cursor_path": "updated_at", "start_param": "since", "cursor_type": "datetime" },
      },
    },
  ],
}
```

Credentials are **never** embedded inline in the manifest — the manifest is non-secret and
round-trips to the client. Secret values live in the dedicated `auth_*` config fields (encrypted in
`job_inputs`, redacted from API reads) and are rejoined into `client.auth` at sync time by
`_inject_auth_secrets`.

## Auth

The manifest's `client.auth.type` selects one of four authenticators. Non-secret fields go in the
manifest; the matching secret goes in the indicated `auth_*` field.

| `type`       | Manifest (non-secret) fields                                                                                | Secret field                               |
| ------------ | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| `bearer`     | —                                                                                                           | `auth_token`                               |
| `api_key`    | `name`, `location` (`header`/`query`/`param`/`cookie`)                                                      | `auth_api_key`                             |
| `http_basic` | `username`                                                                                                  | `auth_password`                            |
| `oauth2`     | `token_url`\*, `client_id`, `grant_type`, `scopes`, `access_token_name`, `expires_in_name`, `header_prefix` | `auth_client_secret`, `auth_refresh_token` |

\* `token_url` is required for `oauth2` and is SSRF-vetted (host safety + https-on-cloud) the same
as `base_url` and every resource URL. Changing it forces the secrets to be re-entered (retarget guard).

### OAuth2

Supports the `client_credentials` and (non-rotating) `refresh_token` grants. The access token is
minted from the token endpoint at sync time and cached in-memory until expiry — nothing is
persisted, so providers that rotate single-use refresh tokens (e.g. QuickBooks/Intuit) are not yet
supported. Credentials are pasted directly (there is no browser OAuth connect flow); obtain a
`refresh_token` / client credentials out-of-band first.

`grant_type` defaults to `refresh_token`. Defaults: `access_token_name="access_token"`,
`expires_in_name="expires_in"`, `header_prefix="Bearer"` (set e.g. `"Zoho-oauthtoken"` for Zoho).

**client_credentials** (e.g. PayPal, Zoom, Auth0 confidential app):

```jsonc
{
  "client": {
    "base_url": "https://api.example.com/v1/",
    "auth": {
      "type": "oauth2",
      "token_url": "https://auth.example.com/oauth/token",
      "grant_type": "client_credentials",
      "client_id": "abc123",
      "scopes": ["read"],
    },
  },
  "resources": [{ "name": "orders", "endpoint": { "path": "orders" } }],
}
```

…with `auth_client_secret` set in the secret field.

**refresh_token** (e.g. Zoho CRM): same block with `"grant_type": "refresh_token"`, plus
`auth_refresh_token` set in the secret field.
