# PostHog Desktop: status and next steps

The long-term goal is to merge PostHog Code (github.com/posthog/code) into this repo and ship a combined desktop app. This package is the first step: PostHog itself running as an Electron app.

## Done

- [x] `@posthog/desktop` workspace package under `products/desktop/` (Electron 42, esbuild, TypeScript, zero runtime deps)
- [x] Local loopback server (`src/main/server/backend.ts`) that serves the built frontend from `frontend/dist`, fully offline
  - generated `index.html` replicating the esbuild chunk-loader contract, without any Django templating (`src/main/server/html.ts`)
  - static assets with immutable caching for hashed chunks and path-traversal protection
- [x] Cloud API proxy: backend paths (`/api/`, `/_preflight`, `/uploaded_media/`, ...) forwarded to the configured region with the personal API key as a bearer token; cookies stripped both ways; the key never reaches the renderer
- [x] Region selection: US Cloud, EU Cloud, or a custom host (self-hosted / local dev), switchable in the shell UI
- [x] Sign-in with a personal API key, verified against `/api/users/@me/` from the main process; stored encrypted with Electron `safeStorage`
- [x] Offline support: app shell and static assets load with no internet; `/_preflight/`, `/api/users/@me/` and `/api/organizations/@current/` responses cached on disk and served stale when the cloud is unreachable; settings fully local
- [x] Shell UI (sign-in, region, account, sign-out) served from a local file, working offline
- [x] Security hardening: sandboxed renderer, context isolation, minimal preload API, window-open and navigation lockdown (external links go to the system browser)
- [x] Window state persistence, app menu (settings, zoom, devtools), single-instance lock, separate dev/prod userData dirs
- [x] Unit tests for the server (routing, proxy auth, offline cache, traversal) and HTML generation via `node:test`; `pnpm --filter=@posthog/desktop test`
- [x] Smoke-tested against real `us.posthog.com`: preflight proxying, auth errors, SPA routes, static chunks

## Next steps

### Auth

- [ ] OAuth (PKCE) sign-in instead of pasted personal API keys: register per-region public OAuth client IDs (like PostHog Code has), open the system browser, receive the callback via a `posthog://` deep link or loopback redirect. The frontend already has most of the plumbing in `frontend/src/lib/oauth/oauthClient.ts`, but it is DEBUG-gated server-side today
- [ ] Token refresh + "network error vs auth error" distinction so flaky networks never sign the user out
- [ ] Multi-account / multi-region switching without re-entering credentials

### Frontend integration

- [ ] A `desktop` flag in the app context / a `getDesktopBridge()` seam so the SPA can detect it runs in the desktop app (hide the region switcher, add native menus and notifications, deep links)
- [ ] Handle endpoints that need session auth rather than a personal API key (e.g. some billing routes) gracefully
- [ ] Per-scene chunk preload map (the Django index.html embeds one; the desktop server could read it from the build metafile)
- [ ] Websocket/livestream proxying if `livestream_host` requests need auth headers

### Offline

- [ ] Expand the offline cache to more bootstrap endpoints (projects, feature flag definitions, dashboards list) with staleness indicators in the UI
- [ ] Queue mutating requests made while offline and replay on reconnect (or block them with clear UI)
- [ ] Connectivity service with an explicit offline banner (PostHog Code has a good reference implementation)

### Packaging and distribution

- [ ] `electron-builder` packaging: bundle `frontend/dist` as `extraResources`, per-platform targets (dmg/nsis/AppImage), `electronLanguages` trimming
- [ ] macOS signing + notarization, Windows signing; release CI workflow (PostHog Code's `code-release.yml` is the model: draft release pre-creation, packaged-app smoke test, checksums)
- [ ] Auto-update via `electron-updater` with GitHub Releases
- [ ] `posthog://` deep links (protocol registration, second-instance/open-url handling)

### Merging PostHog Code

- [ ] Adopt the tRPC-over-IPC pattern from posthog/code (`packages/electron-trpc`) once the IPC surface grows beyond a handful of channels
- [ ] Share the region/auth/platform-adapter layers with PostHog Code, then bring its UI in as a scene/panel of the combined app
- [ ] Crash recovery (renderer auto-reload with crash-loop breaker) and Chromium file logging

### Housekeeping

- [ ] Self-capture analytics for the desktop app itself (opt-in, `JS_POSTHOG_API_KEY` injection)
- [ ] E2E test that boots the packaged app with Playwright (needs a display in CI)
- [ ] Decide the trust-policy story for adding Electron-adjacent deps (`pnpm install` needed `--config.trustPolicyIgnoreAfter=129600` for old transitive packages)
