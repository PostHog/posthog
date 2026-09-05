# Desktop PR previews

An engineer can add the `desktop-preview` label to a same-repository pull
request and get installable desktop applications connected to an isolated
backend running that PR's code. A tester needs only the PostHog VPN, an
installer, and the login instructions from a PR comment — no local backend, no
checkout, no environment files, no terminal.

Everything on this page is opt-in per PR. Ordinary releases, ordinary preview
environments, and unlabeled PRs are unchanged.

## What a tester gets

Adding `desktop-preview` to an eligible PR provisions one isolated backend
(the same hogland box the `hogbox-preview` label uses) with the desktop
profile, and builds desktop installers from the same commit:

- A sticky PR comment reports progress, the backend URL, the synthetic login,
  and per-platform artifact links. The comment is the single source of state.
- The backend runs the PR's backend code at the exact PR head SHA, with the
  OAuth application and synthetic tester accounts the desktop client needs.
- Installers are signed but not notarized. On macOS, clear the quarantine flag
  once (the PR comment names the exact application):

  ```sh
  xattr -dr com.apple.quarantine "/Applications/PostHog Preview PR 123.app"
  ```

- The preview app coexists with the normal PostHog app and with previews of
  other PRs: its name, data directory, URL scheme, and OAuth callback are all
  derived from the PR number, so two previews never collide and a preview never
  steals the production app's OAuth callback.
- After a push, the backend moves to the new commit. Download a fresh installer
  from the updated comment; an old installer detects the revision mismatch and
  says so instead of silently testing a stale revision. Backend test data and
  sessions can reset when the box is replaced.

## Requirements and limits

- **VPN required.** Preview backends are reachable only over the PostHog VPN.
  Public distribution is not part of this version.
- **Same-repository PRs only.** Fork PRs never receive provisioning or
  installer signing — fork code must never run with provisioning credentials in
  scope.
- **macOS quarantine stays.** First-version installers are signed but not
  notarized; Gatekeeper reports the app as damaged until the flag is cleared.
- **Updates are disabled.** A preview app never polls or downloads from the
  stable release feed, including the manual "check for updates" path. Each push
  means a fresh download.
- **AI gateway calls are unavailable unless configured.** When the preview
  manifest's gateway is `unavailable`, agent model calls fail with a clear
  message rather than falling back to a production gateway. The PR comment
  states which capabilities were verified.

## How the app knows its backend

The provisioning job emits a validated JSON manifest
(`products/desktop/packages/shared/src/desktop-preview.ts` defines the schema)
containing only public data: the backend origin, the OAuth client id, the PR
number, the commit SHA, feature-flag overrides, and the gateway configuration.
The build bakes it into the app as a build-time constant
(`POSTHOG_DESKTOP_PREVIEW_CONFIG` names the file at build time).

Rules the schema and build enforce:

- The backend origin is HTTPS, credential-free, and a bare origin.
- The app identity (product name, bundle id, URL scheme, user-data directory,
  OAuth redirect URI) is **derived** from the PR number, never read from
  PR-authored JSON.
- A release build fails closed if preview configuration is present; a preview
  build fails closed if it is absent or invalid. No build is ever
  half-preview.
- The stored session records the deployment identity (origin + client id). A
  preview app discards stored credentials when the deployment changed — they
  are never sent to a different backend.
- Preview sessions never resolve to a production region, and an ordinary build
  never resumes a preview session.

The client checks `/static/desktop-preview/deployment.json` on the backend at
startup: the document names the PR, the exact backend commit SHA, and a
deployment generation. A SHA different from the one baked into the installer
means the backend moved and a newer installer is required.

## Labels

| Label | Effect |
| --- | --- |
| `desktop-preview` | Provision the desktop profile backend and build preview installers. Works on draft PRs. |
| `hogbox-preview` | Backend + web frontend preview (existing behavior). Shares the same backend with `desktop-preview`. |
| `no-preview` | Explicit opt-out; suppresses both. |
| `desktop-build-installer` | Ordinary signed test installers (existing behavior). Independent of previews. |

Removing `desktop-preview` retires the desktop packaging but keeps the backend
when `hogbox-preview` or auto-preview still wants it. Closing the PR tears down
everything. Re-running the manual workflow dispatch reconciles the current head.

## Consuming the infrastructure from a feature branch

The infrastructure ships on master. A feature branch opts into extra preview
capabilities through an optional `products/desktop/preview.json`:

```json
{
  "schemaVersion": 1,
  "capabilities": ["canvas-compiler"],
  "featureFlags": {
    "posthog-desktop-sketchpads": true
  }
}
```

- `capabilities` names extra background services the preview backend should
  run (unknown names fail clearly). Capability implementations live in trusted
  preview tooling; the file never carries commands, mounts, or secrets.
- `featureFlags` are boolean overrides applied on top of the app's feature-flag
  service before first render. `false` overrides hold too. Production builds
  reject overrides.
- Absence of the file means the baseline desktop profile.

A branch without this infrastructure (unrebased, predating it) gets a clear
"update this branch with desktop preview infrastructure" response and no
provisioning, never a misconfigured build.

## Where the code lives

| Concern | Location |
| --- | --- |
| Manifest schema + identity derivation | `packages/shared/src/desktop-preview.ts` |
| Build-boundary manifest loader | `apps/code/scripts/preview-config.mts` |
| Packaged identity, updater gating, scheme registration | `apps/code/src/main/preview.ts`, `bootstrap.ts`, `services/deep-link/`, `platform-adapters/electron-updater.ts` |
| Preview auth target (session + deployment identity) | `packages/core/src/auth/` |
| Preview revision check | `packages/core/src/auth/previewRevision.ts` |
| Platform port | `packages/platform/src/preview-deployment.ts` |
| Sign-in + badge UI | `packages/ui/src/features/auth/` |
| Provisioning (OAuth seed, metadata, readiness) | `tools/hogbox-preview/hogbox_preview/desktop_profile.py`, `stack.py` |
| Label semantics | `.github/scripts/desktop/desktop-preview-decision.js` |
| Workflows | `hogbox-preview-env.yml`, `desktop-build-installers.yml`, `desktop-build-test.yml` |
