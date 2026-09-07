# Desktop PR previews

Add `desktop-preview` to an open, same-repository PR to build desktop installers connected to that PR’s isolated backend.
Draft PRs support this label too.
The backend and installers use the same pinned commit.
The provisioning controller runs from the default branch, so this infrastructure must land on master before other branches can use it.

## Test a PR

1. Connect to the PostHog VPN.
2. Add `desktop-preview` to the PR and wait for its preview comment.
3. Download an installer for your platform from the linked workflow artifacts.
4. Sign in with `desktop-tester-1@example.com` or `desktop-tester-2@example.com`, using password `posthog-desktop-preview`.

Both test accounts share an isolated organization and project.
The preview has a separate application name, callback scheme, and data directory for each PR.
It can run alongside the normal desktop app and other previews.

The macOS installers are signed but not notarized.
If macOS blocks the app, replace `123` with your PR number and run:

```sh
xattr -dr com.apple.quarantine "/Applications/PostHog Preview PR 123.app"
```

## Preview limits

- Agent model calls are unavailable. Preview credentials cannot fall back to a production gateway.
- Automatic updates and product analytics are disabled.
- The backend can sleep when idle. Open its URL in your browser to wake it before retrying login.
- Download a new installer after pushing to the PR. Authenticated requests verify the backend revision, caching a successful check for up to 30 seconds.
- Backend replacement can reset test data and sessions. An installer for a different backend origin or OAuth client requires a new sign-in.
- Workflow artifacts expire after seven days. Preview features that need additional services are unsupported until their provisioning is implemented.

The desktop profile sets `DESKTOP_PREVIEW=1` to let its synthetic accounts pass the desktop billing gate.
This default-off setting applies only when `CLOUD_DEPLOYMENT` is unset or `LOCAL`; hosted cloud deployments ignore it.
Authentication is still required.

## Labels and lifecycle

| Label | Behavior |
| --- | --- |
| `desktop-preview` | Build the desktop backend profile and installers, including for drafts. |
| `hogbox-preview` | Build a web/backend preview using the same backend. |
| `no-preview` | Suppress both preview paths. |
| `desktop-build-installer` | Build ordinary test installers when `desktop-preview` is absent. |

Unrelated label changes do not rebuild previews.
Removing `desktop-preview` cancels its active packaging and removes its download links from the preview comment.
Existing artifacts remain available until they expire.
The backend stays when `hogbox-preview` or automatic frontend preview eligibility still requires it.
Removing the last source of preview demand tears down the backend.
Closing the PR also tears it down through the existing PR cleanup workflow.

## Build contract

`POSTHOG_DESKTOP_BUILD_KIND=preview` requires `POSTHOG_DESKTOP_PREVIEW_CONFIG` to point to a public JSON manifest.
`POSTHOG_DESKTOP_PREVIEW_PR` and `POSTHOG_DESKTOP_PREVIEW_SHA` must match that manifest.
The manifest contains its schema version, repository, PR number, commit SHA, HTTPS backend origin, and public OAuth client ID.
Unknown fields, URL credentials, unsupported schemas, and mismatched build identities fail validation.
Ordinary builds reject preview input.

The backend publishes `/static/desktop-preview/deployment.json` before starting its web process.
Readiness requires a real tester login, PKCE authorization and token exchange, an authenticated user read, and desktop project access.
Branches without `desktopPreviewConfigVersion: 1` in the desktop app package must update from master before building previews.

## Implementation

- Manifest and application identity: `packages/shared/src/desktop-preview.ts`
- Build validation: `apps/code/scripts/preview-config.mts`
- Authentication and revision verification: `packages/core/src/auth/`
- Provisioning: `tools/hogbox-preview/hogbox_preview/desktop_profile.py` and `stack.py`
- Lifecycle: `.github/scripts/desktop/desktop-preview-decision.js` and `.github/workflows/hogbox-preview-env.yml`
- Packaging: `.github/workflows/desktop-build-installers.yml`
