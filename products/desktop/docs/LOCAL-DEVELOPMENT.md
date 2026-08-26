# Connecting the Desktop App to a Local PostHog Instance

This guide walks you through running the desktop app's dev build against a local PostHog instance (localhost:8010).

## Prerequisites

- A running local PostHog instance at `http://localhost:8010` ([PostHog local development docs](https://posthog.com/handbook/engineering/developing-locally))
- Node.js 22+
- pnpm 10+

## 1. Set up the OAuth application in PostHog

The desktop app authenticates with PostHog via OAuth. Your local PostHog instance needs an OAuth application registered for the app to connect to it.

### Option A: Generate demo data (easiest)

PostHog's demo data generator creates a pre-configured OAuth application with the correct client ID:

```bash
# In your PostHog repo
python manage.py generate_demo_data
```

This creates an OAuth application with:
- **Client ID**: `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ`
- **Redirect URIs**: includes `http://localhost:8237/callback` and `http://localhost:8239/callback`

### Option B: Create the OAuth application manually via Django admin

1. Go to http://localhost:8010/admin/posthog/oauthapplication/
2. Click **Add OAuth Application**
3. Set these fields:
   - **Name**: `PostHog Desktop` (or whatever you like)
   - **Client ID**: `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ` — this must match the `POSTHOG_DEV_CLIENT_ID` in the app's source
   - **Client type**: `Public` (the app is an Electron desktop app)
   - **Authorization grant type**: `Authorization code`
   - **Redirect URIs**: `http://localhost:8237/callback http://localhost:8239/callback`
   - **Algorithm**: `RS256`
4. Save

> **Important**: The Client ID must be exactly `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ` — this is hardcoded in the app as the Dev region client ID (see `apps/code/src/shared/constants/oauth.ts`).

## 2. Configure RSA keys in PostHog

OAuth token signing requires an RSA private key. In your PostHog repo:

```bash
# Copy the RSA key from .env.example to your .env
grep OIDC_RSA_PRIVATE_KEY .env.example >> .env
```

Or generate a new one:

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -outform PEM | \
  awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}'

# Add to your PostHog .env as OIDC_RSA_PRIVATE_KEY="<generated_key>"
```

## 3. Clone and run the app

Already working in the posthog/posthog monorepo? Skip the clone: the app lives at `products/desktop`. Note it needs Node 22 (see `.node-version`), not the Node version the monorepo's flox environment provides, so switch with your version manager first.

```bash
cd products/desktop
pnpm install
cp .env.example .env
pnpm dev
```

Starting fresh? Clone the monorepo. The standalone PostHog/code repo is archived and no longer receives changes.

```bash
git clone https://github.com/PostHog/posthog.git
cd posthog/products/desktop
pnpm install
cp .env.example .env
pnpm dev
```

## 4. Connect to your local instance

1. When the app opens, select the **Dev** region on the login screen (in addition to US & EU, the dev build shows a Dev option that points to `localhost:8010`)
2. This will redirect you to your local PostHog instance for OAuth authorization
3. Authorize the application and select the project/organization access level
4. You'll be redirected back to the app, now connected to your local PostHog

## How it works

The dev build includes a "Dev" cloud region that maps to:
- **API URL**: `http://localhost:8010`
- **OAuth Client ID**: `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ`

This is defined in `apps/code/src/shared/constants/oauth.ts`. The Dev region only appears when running the dev build (`pnpm dev`), not in production releases.

## Dev console commands

Open devtools in the dev build and type:

- `__codeInboxDemo()` — show help
- `__codeInboxDemo('seed')` — fill the inbox with fake data
- `__codeInboxDemo('seed', 'artefacts-unavailable')` — fake data, artefacts-unavailable mode
- `__codeInboxDemo('seed', 'empty')` — fake data, empty state
- `__codeInboxDemo('clear')` — remove fake data, go back to real API

Source: `apps/code/src/renderer/features/inbox/devtools/inboxDemoConsole.ts`.

## Feature flags in local dev

Feature flags are read through posthog-js, configured by the `VITE_POSTHOG_*`
vars in `.env`. By default these point at PostHog's internal analytics instance,
so flags you create locally never resolve in the dev build.

To point the flags/analytics client at your local PostHog so locally-synced
flags take effect:

```bash
# In your PostHog repo: create + enable all frontend-defined flags locally
python manage.py sync_feature_flags

# In this repo: rewrite VITE_POSTHOG_* to your local instance, then restart dev
node scripts/use-local-posthog.mjs
pnpm dev
```

`node scripts/use-local-posthog.mjs` auto-reads the project API key from the
surrounding monorepo checkout (or pass it:
`node scripts/use-local-posthog.mjs phc_xxx`, or set `POSTHOG_DIR`). This
only affects the analytics/flags client — the data API still uses the **Dev**
region you pick at login.

> One-off override without changing `.env`: the dev build exposes the client on
> `window.posthog`, so you can run
> `posthog.featureFlags.override({ "mcp-gateway": true })` in the renderer
> console (clear with `posthog.featureFlags.override(false)`).

## Troubleshooting

### Feature flags never enabled (flag-gated UI missing)

If flag-gated surfaces (e.g. the MCP gateway behind `mcp-gateway`) never show up
even though the flag is enabled in your PostHog project, check
`VITE_POSTHOG_API_HOST` in `.env`: it must include the scheme
(`http://localhost:8010`, not `localhost:8010`). posthog-js concatenates the
host into request URLs verbatim, so a scheme-less value produces URLs like
`localhost:8010/flags/…` that the browser rejects as an invalid protocol —
every flag fetch fails silently and `isFeatureEnabled` returns `undefined` for
everything (flags never loaded). Prefer `node scripts/use-local-posthog.mjs`
over hand-editing; it writes the correct form.

To confirm what the running app sees, run in the renderer console (or via CDP):

```js
posthog.config.api_host;                  // must start with http:// or https://
posthog.isFeatureEnabled("mcp-gateway"); // undefined ⇒ flags never loaded
```

`.env` changes need a dev-server restart (`pnpm dev`) to take effect.

### "Invalid client_id" error during OAuth

The OAuth application in your local PostHog must have the client ID `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ`. Verify at http://localhost:8010/admin/posthog/oauthapplication/.

### "OAuth error: invalid_scope"

PostHog Desktop requests the wildcard scope `*` (see `OAUTH_SCOPES` in
`packages/shared/src/oauth.ts`). PostHog's OAuth server only grants `*` at
`/authorize` when the OAuth application's **scope ceiling is empty** — this is
the grandfathering path for the PostHog Desktop client. If the application has any
explicit `scopes` or `optional_scopes` configured, the wildcard is rejected with
`invalid_scope`.

Fix: clear the scope ceiling on your local OAuth application so it matches the
production app. Either edit it at
http://localhost:8010/admin/posthog/oauthapplication/ (empty the **Scopes** and
**Optional scopes** fields), or run in your PostHog repo:

```bash
python manage.py shell -c "
from posthog.models.oauth import OAuthApplication
app = OAuthApplication.objects.get(client_id='DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ')
app.scopes = []
app.optional_scopes = []
app.save()
print('cleared scope ceiling for', app.client_id)
"
```

Then retry login. (Do not add `*` to the ceiling — an explicit ceiling never
grants the wildcard, even if `*` is listed.)

### "Redirect URI mismatch"

Make sure the OAuth application's redirect URIs include `http://localhost:8237/callback` and `http://localhost:8239/callback`. Check for trailing slashes.

### OAuth authorization page fails to load

Ensure your local PostHog instance is running at `http://localhost:8010` and that the RSA key is configured (see step 2).

### Existing projects not showing up

After connecting, the app will show projects from your local PostHog instance. If you need test data, run `python manage.py generate_demo_data` in your PostHog repo.

### 431 error

Clean up `localhost` cookies in your browser, as you probably accumulated too many/large cookies for the server to accept as the request headers.

## Further reading

- [PostHog OAuth Development Guide](https://github.com/PostHog/posthog/blob/master/docs/published/handbook/engineering/oauth-development-guide.md) — full OAuth spec, scopes, token introspection, and more
