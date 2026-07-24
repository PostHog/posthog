# @posthog/web

Browser host for PostHog Code. Boots the same `@posthog/ui` shell and
`@posthog/core` services as the desktop app, with web platform adapters —
no Electron, no local workspace-server. Scope today: auth + cloud tasks
(local workspaces, terminal, and local git need a workspace backend and are
out of scope for the web host's first iteration).

## Run

```bash
pnpm --filter @posthog/web dev   # Vite on http://localhost:5273
```

No separate backend process: the host router slice runs in the browser
(`web-host-router.ts`), served over tRPC's `unstable_localLink`
(`web-trpc.ts`). `auth`, `cloudTask`, and `analytics` are the real routers
backed by in-browser `AuthService` / `CloudTaskService` (both are
host-agnostic core code); the rest are stubs that return benign empties.
Procedures outside the slice fail with NOT_FOUND at call time — that is the
to-do list for widening the web surface.

## Testing

```bash
pnpm --filter @posthog/web test:e2e   # Playwright: happy-path browser e2e
```

- **`tests/e2e/`** drives stock Chromium against the Vite dev server (Playwright
  starts it). Scope is the hermetic happy path up to the OAuth wall — boot,
  container wiring, onboarding → sign-in card, and the `/callback` relay — since
  real login needs PostHog cloud and a popup IdP. Runs in CI (`test.yml`),
  reusing the desktop suite's cached Chromium.
- The boot spec doubles as the host-capability guard: `web-container.ts` runs
  `assertHostCapabilities(REQUIRED_HOST_CAPABILITIES)` at container load, so an
  unbound capability throws before the app mounts and fails the boot spec. (A
  jsdom unit test that imported the whole composition root was tried but dropped
  — evaluating the entire app graph took ~30s+ per run, and the e2e already
  covers it.) The capability *mechanism* is unit-tested in
  `@posthog/di` (`hostCapabilities.test.ts`).

## Auth

`WebOAuthFlowService` (`web-oauth-flow.ts`) implements the core
`IAuthOAuthFlowService` with a browser PKCE flow: popup to
`{cloud}/oauth/authorize`, redirect back to `{origin}/callback`, code relayed
to the opener tab over a BroadcastChannel, token exchange via fetch. Session
persistence is localStorage (`web-auth-adapters.ts`); the refresh token is
encrypted at rest with AES-GCM under a **non-extractable** Web Crypto key held
in IndexedDB (`webAuthTokenCipher`). The key round-trips through structured
clone but its raw bytes are never exposed to JS, so a stolen localStorage dump
can't be decrypted offline — matching the bar the desktop host's machine-bound
cipher sets. A live XSS payload can still ask the key to decrypt while it runs
on the page (httpOnly cookies would need server-side sessions the cloud host
doesn't have). Tokens written by the earlier plaintext build fail to decrypt
and are cleared, forcing a clean re-auth.

## Hosting

Build a static bundle and serve it:

```bash
pnpm --filter @posthog/web build   # Vite output: apps/web/dist
```

Serve `dist/` as a single-page app with a fallback to `index.html` for unknown
paths. The OAuth popup lands on the real path `/callback` (`OAUTH_CALLBACK_PATH`
in `web-oauth-flow.ts`, dispatched in `main.tsx`), which must load the SPA to
relay the code back to the opener tab. The app's own routes use hash history, so
`/callback` is the only real path that needs the fallback.

The build is code-split: vendor libraries into cacheable groups (`manualChunks`
in `vite.config.ts`) and each route's component into its own lazy chunk (the
TanStack Router plugin's `autoCodeSplitting`, mirroring `apps/code`), so a screen
downloads only when navigated to. All emitted assets are content-hashed — serve
`dist/assets/` with a long-lived immutable `Cache-Control` and only `index.html`
short-lived, so returning users re-download just the chunks that changed.

The steps below are one-time setup for a deployed origin. None block the app
from booting, but auth, attachments, and integrations each need one.

### Environment variables

All are Vite build-time vars (`import.meta.env.*`), baked in at build time.

| Var | Required | Purpose |
| --- | --- | --- |
| `VITE_POSTHOG_API_KEY` | Recommended | Real `phc_…` project key. Enables posthog-js analytics, error/rejection capture, session recording, and real feature flags. The guard in `main.tsx` requires the `phc_` prefix; without it posthog stays uninitialized and the tracker/analytics service no-op, leaving only the host-forced `SYNC_CLOUD_TASKS_FLAG` on (every other flag reads `false`). |
| `VITE_POSTHOG_API_HOST` | No | posthog-js ingestion host. Default `https://internal-c.posthog.com`. |
| `VITE_POSTHOG_UI_HOST` | No | posthog-js UI host. Default `https://us.i.posthog.com`. |
| `VITE_POSTHOG_ACCESS_TOKEN_OVERRIDE` | No | Dev/test only: a static access token that bypasses the OAuth flow (`AUTH_TOKEN_OVERRIDE`). Leave unset in production. |

Session recording turns on whenever posthog-js initializes (any build with a
real key); automatic unhandled-error/rejection/console capture is additionally
gated to non-dev (production) builds (`capture_exceptions` in
`posthogAnalyticsImpl.ts`).

### OAuth redirect URI registration — required for sign-in

The web host reuses the Code ("Array") OAuth application client ids
(`packages/shared/src/oauth.ts`). Each region stores its app's `redirect_uris`
as database rows (Django admin → OAuth applications), and they must include:

- `https://<web-origin>/callback` for the deployed host. `http` is rejected for
  non-loopback hosts by `OAuthApplication` redirect validation, so the origin
  must be HTTPS.
- `http://localhost/callback` (portless) for local dev — PostHog's authorize
  view extends RFC 8252 §7.3 loopback port flexibility to `localhost`
  (`posthog/api/oauth/views.py: validate_redirect_uri`), so the portless form
  matches the Vite dev server on any port. If desktop dev builds can already
  sign in to the region, check whether the registered localhost URI is portless
  or pinned to `:8237`.

A CIMD client (the `raycast_metadata.py` / `wizard_metadata.py` pattern in
`posthog/api/oauth/`) is NOT suitable: CIMD registrations are capped to
unprivileged scopes, and Code requires `scope=*` like the desktop app.

### S3 artifact-bucket CORS — required for attachment uploads

Composer attachments upload straight from the browser via an S3 presigned POST
(`.../artifacts/prepare_upload/` returns the presigned post, then a `POST` to
`s3.<region>.amazonaws.com/<bucket>`). The bucket
(`posthog-cloud-prod-us-east-1-app-assets` for US) must return
`Access-Control-Allow-Origin` for the web origin or the browser blocks the
response — the POST itself returns `204` (it succeeds server-side) but `fetch`
rejects with a bare `NetworkError`. Desktop (Electron/Node `fetch`) is not
subject to CORS, so this is web-only.

Add the deployed web origin (and `http://localhost:5273` for dev) with the
`POST` method to the bucket's CORS config. Until then, attaching + preview work
but sending a task with an attachment fails at the upload step.

### `posthog_web` integration connect origin — required for Slack / GitHub connect

PostHog brokers the Slack/GitHub OAuth server-side and, on completion, redirects
to a target chosen by the `connect_from` value (`posthog_code` →
`posthog-code://…`, `posthog_mobile` → `posthog://…`) — a per-known-client
mapping, not an open redirect. The web host's `startFlow` opens
`.../integrations/authorize/?kind={slack|github}&next=…&connect_from=posthog_web`
in a tab; the backend needs a `posthog_web` mapping for the flow to complete. No
callback relay is required because the integration is created server-side and the
connect hooks refetch `getIntegrations()` on window-focus. See Known gaps for
what remains once the mapping exists.

### CORS — no action needed

Verified against `us.posthog.com`: `/oauth/token` answers preflight with the
request origin allowed, and `/api/*` responds `access-control-allow-origin: *`
with `authorization` in the allowed headers. The agent-proxy stream service has
a CORS origin allowlist (`TASKS_AGENT_PROXY_CORS_ORIGINS` in
`PostHog/posthog/services/agent-proxy`), and `CloudTaskService` falls back to
the CORS-open Django stream leg regardless.

## Known gaps

Limitations that remain even after the hosting setup above — each needs a code
or backend change, not just configuration.

- **Slack / GitHub connect** is client-wired (`startFlow` opens the authorize
  URL; the connection is detected via a window-focus refetch of
  `getIntegrations()`, not a callback relay) but gated on backend support for the
  `posthog_web` connect origin (see Hosting). Even with that mapping, the GitHub
  *user* flow (`POST /api/users/@me/integrations/github/start/`) hardcodes
  `connect_from: "posthog_code"` in `@posthog/api-client` and returns **400** on
  web — it needs a host-parameterized `connect_from`. Where a project already has
  the integration connected, the settings pages render the connected/manage state
  correctly.
- **Per-device stores** (cloud workspaces, archive, pins, browser tabs) are
  localStorage-only — not durable across devices or a site-data clear. Desktop
  persists these in SQLite; the browser host needs server-side state to match.
- **Skill dependency expansion** is a passthrough: a skill that declares
  `dependencies:` on other skills won't pull them in automatically (pick them
  explicitly). This is a pipeline gap, not just a web gap — `exportSkill` strips
  SKILL.md frontmatter and the team-skills API has no `dependencies` field, so
  the dependency list never reaches any client (desktop only expands local
  on-disk skills). Needs `dependencies` carried end-to-end through
  export → publish → the LlmSkill API (backend) → `fetchSkillForInstall`.
