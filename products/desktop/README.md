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

Sign in by choosing a region (US Cloud, EU Cloud, or a custom host) and clicking "Sign in with browser": the app opens PostHog Cloud's OAuth consent flow in your system browser (password, Google or SAML — whatever your account uses), receives the callback on its local loopback server, and stores the refresh token encrypted with `safeStorage`. Access tokens are refreshed automatically before they expire.

Alternatively, use "Use a personal API key instead" and paste a key created in PostHog under Settings › Personal API keys (give it all scopes you want the app to be able to use). A personal API key is the only option for custom hosts, unless `POSTHOG_DESKTOP_OAUTH_CLIENT_ID` points at an OAuth app registered on that instance.

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

Local and PR builds are unsigned: `scripts/after-pack.cjs` applies an ad-hoc signature, which is required for the app to launch on Apple Silicon at all.
Because of that, macOS quarantines a downloaded unsigned app.
To open it: right-click the app › Open, or run `xattr -d com.apple.quarantine /Applications/PostHog.app`.

CI builds installers for every PR that touches `products/desktop/` (`.github/workflows/build-desktop-app.yml`):
the frontend is built once on Linux and shared as an artifact, then per-OS jobs package it and upload the macOS DMG (`posthog-desktop-macos-arm64`) and the Windows NSIS installer (`posthog-desktop-windows-x64`) as workflow-run artifacts.
On master pushes and manual dispatches, the macOS build is signed with the PostHog Inc. Developer ID certificate and notarized — the same org secrets PostHog Code releases with (`APPLE_CODESIGN_CERT_BASE64`, `APPLE_CODESIGN_CERT_PASSWORD`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`) — so that DMG opens without any quarantine workarounds.
If the secrets are absent the non-PR build degrades to unsigned rather than failing.
The Windows installer is always unsigned for now (no Windows code-signing cert), so SmartScreen warns on first run: "More info" › "Run anyway".

## Fork: daily sync and releases

Actual desktop releases are published from the fork `mariusandra/posthog`, where the `desktop` branch (the fork's default branch) is upstream master plus the desktop work.
The upstream PostHog/posthog repo intentionally carries no desktop release secrets and publishes nothing; the two workflows below are gated to the fork (`if: github.repository == 'mariusandra/posthog'`) and are inert upstream.

- `desktop-sync.yml` merges upstream master into `desktop` daily; the OpenAI Codex CLI resolves conflicts and merge fallout following the `syncing-desktop-fork` skill (`.agents/skills/syncing-desktop-fork/SKILL.md`). Only desktop tests (and frontend typecheck when relevant) gate the sync — backend and e2e suites are deliberately not run on the fork.
- `desktop-release.yml` runs after each sync (and on pushes to `desktop`): if `version` in `products/desktop/package.json` has no `desktop-v<version>` release yet, it builds the signed + notarized macOS DMG and the Windows installer on GitHub-hosted runners and publishes them as a GitHub release on the fork. Bumping the version field is the release trigger.

Fork setup (one-time): enable Actions on the fork, enable the two workflows (scheduled workflows in forks start disabled), and add the repository secrets `OPENAI_API_KEY` (sync), `APPLE_CODESIGN_CERT_BASE64`, `APPLE_CODESIGN_CERT_PASSWORD`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, and `APPLE_TEAM_ID` (release signing + notarization).

See [TODO.md](./TODO.md) for what's done and what's next.
