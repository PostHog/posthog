# PostHog Desktop

An Electron app that runs the PostHog frontend natively, straight from this repo's build output, against PostHog Cloud (US or EU) or any self-hosted instance.

## How it works

```text
┌────────────────────────── Electron ───────────────────────────┐
│                                                                │
│  Renderer (sandboxed)                Main process              │
│  ┌──────────────────────┐            ┌──────────────────────┐  │
│  │ PostHog frontend SPA │  /static ▶ │ Local loopback server│  │
│  │ (frontend/dist,      │  /api    ▶ │  · serves dist       │  │
│  │  loaded from         │            │  · proxies API to    │──┼──▶ us/eu.posthog.com
│  │  http://127.0.0.1:*) │            │    cloud + bearer key│  │    (or custom host)
│  └──────────────────────┘            │  · offline cache     │  │
│  ┌──────────────────────┐            └──────────────────────┘  │
│  │ Shell UI (sign-in,   │  IPC ────▶ settings, sign-in,        │
│  │ region, settings)    │            safeStorage secrets       │
│  └──────────────────────┘                                      │
└────────────────────────────────────────────────────────────────┘
```

- The main process runs a loopback HTTP server that plays Django's role locally: it serves the built frontend (`frontend/dist`) and a generated `index.html` without `POSTHOG_APP_CONTEXT`, so the app bootstraps itself from `/_preflight/` and `/api/users/@me/`.
- Backend paths (`/api/`, `/_preflight`, `/uploaded_media/`, ...) are proxied to the configured cloud region with the personal API key attached as a bearer token. The key is encrypted at rest with Electron `safeStorage` and never reaches the renderer.
- The app shell, all static assets, and the settings UI work with no internet connection. Key bootstrap responses are cached on disk and served stale when the cloud is unreachable.

## Running it

```bash
# 1. Build the PostHog frontend (once, and after frontend changes)
pnpm turbo build --filter=@posthog/frontend

# 2. Start the desktop app (downloads the Electron binary on first run)
pnpm --filter=@posthog/desktop start
```

Sign in by choosing a region (US Cloud, EU Cloud, or a custom host) and pasting a personal API key, created in PostHog under Settings › Personal API keys. Give the key all scopes you want the app to be able to use.

## Development

```bash
pnpm --filter=@posthog/desktop typecheck
pnpm --filter=@posthog/desktop test        # node:test, no Electron needed
pnpm --filter=@posthog/desktop build       # bundle main/preload/shell with esbuild
```

`POSTHOG_DESKTOP_FRONTEND_DIST=/path/to/dist` overrides where the frontend build is loaded from.

## Packaging

```bash
# Build the frontend first (see above), then:
pnpm --filter=@posthog/desktop package
```

This bundles the app with [electron-builder](https://www.electron.build/) (config in `electron-builder.yml`) into `release/`:
the built frontend is embedded as the `frontend-dist` resource (sourcemaps stripped), so the packaged app is fully self-contained.

The build is currently unsigned: there is no signing identity yet, so `scripts/after-pack.cjs` applies an ad-hoc signature, which is required for the app to launch on Apple Silicon at all.
Because of that, macOS quarantines the downloaded app.
To open it: right-click the app › Open, or run `xattr -d com.apple.quarantine /Applications/PostHog.app`.

CI builds the DMG for every PR that touches `products/desktop/` (`.github/workflows/build-desktop-app.yml`) and uploads it as the `posthog-desktop-macos-arm64` artifact on the workflow run.

See [TODO.md](./TODO.md) for what's done and what's next.
