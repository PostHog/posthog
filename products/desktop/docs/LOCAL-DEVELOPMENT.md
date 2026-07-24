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

```bash
git clone https://github.com/PostHog/code.git
cd code
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
so flags you create locally never resolve in the dev build (and flag-gated UI —
e.g. the agent-platform surface behind the `agent-platform` flag — stays hidden).

To point the flags/analytics client at your local PostHog so locally-synced
flags take effect:

```bash
# In your PostHog repo: create + enable all frontend-defined flags locally
python manage.py sync_feature_flags

# In this repo: rewrite VITE_POSTHOG_* to your local instance, then restart dev
node scripts/use-local-posthog.mjs
pnpm dev
```

`node scripts/use-local-posthog.mjs` auto-reads the project API key from a
sibling `../posthog` checkout (or pass it:
`node scripts/use-local-posthog.mjs phc_xxx`, or set `POSTHOG_DIR`). This
only affects the analytics/flags client — the data API still uses the **Dev**
region you pick at login.

> One-off override without changing `.env`: the dev build exposes the client on
> `window.posthog`, so you can run
> `posthog.featureFlags.override({ "agent-platform": true })` in the renderer
> console (clear with `posthog.featureFlags.override(false)`).

## Troubleshooting

### "Invalid client_id" error during OAuth

The OAuth application in your local PostHog must have the client ID `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ`. Verify at http://localhost:8010/admin/posthog/oauthapplication/.

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
