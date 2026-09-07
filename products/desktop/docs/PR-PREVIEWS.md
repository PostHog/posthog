# Desktop PR previews

Add `desktop-preview` to an open, same-repository PR to build desktop installers connected to that PR's isolated backend.
Draft PRs support this label too.
The provisioning controller runs from the default branch, so this infrastructure must land on master before other branches can use it.

## Test a PR

1. Connect to the PostHog VPN.
2. Add `desktop-preview` to the PR and wait for its preview comment.
3. Download an installer for your platform from the linked workflow run.
4. Sign in with `desktop-tester-1@example.com` or `desktop-tester-2@example.com`, using password `posthog-desktop-preview`.

Both test accounts share an isolated organization and project.
The preview has a separate application name, callback scheme, and data directory for each PR.
It can run alongside the normal desktop app and other previews.

The macOS installers are signed but not notarized.
If macOS blocks the app, replace `123` with your PR number and run:

```sh
xattr -dr com.apple.quarantine "/Applications/PostHog Preview PR 123.app"
```

## What a push does

The backend follows every push: the box behind the stable URL is replaced with the PR's new commit.
Installers rebuild only when the push touches `products/desktop/**` or the installer workflow.
A backend-only push keeps the installer you already have, and the preview comment keeps linking it.
The comment holds the backend and the installers as two separate records, so an installer build that finishes after a later push still adds its links.
The desktop app tolerates a backend that is newer than the installer, the same way the released app tolerates backend deploys.

## Agents in a preview

The preview runs its own LLM gateway inside the box, next to Django.
Every hogbox gets renewable AWS credentials from hogland, so the gateway serves Claude models through Bedrock with no provider keys and no shared PostHog key.
The gateway validates the preview's own tokens against the box's Postgres, so each tester keeps their own identity.
A proxy on the preview URL serves the gateway under `/llm-gateway`.
Only Claude models work in a preview. Codex and other providers do not.

## Preview limits

- Automatic updates and product analytics are disabled.
- The backend can sleep when idle. The first request wakes it, which can take a minute.
- Backend replacement can reset test data and sessions, so you may need to sign in again after a push.
- Workflow artifacts expire after seven days. Re-add the label to build fresh installers.
- Model calls in a preview cost hogland's Bedrock account, the same as agent boxes.

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

A build is a preview build when `POSTHOG_DESKTOP_PREVIEW_CONFIG` points to a public JSON manifest.
`POSTHOG_DESKTOP_PREVIEW_PR` and `POSTHOG_DESKTOP_PREVIEW_SHA` must match that manifest.
The manifest contains its schema version, repository, PR number, commit SHA, HTTPS backend origin, LLM gateway base URL (or null), and public OAuth client ID.
Unknown fields, URL credentials, non-HTTPS URLs, unsupported schemas, and mismatched build identities fail validation.
Ordinary builds reject preview input.

Inside the app the preview backend is the `preview` region.
Each process registers the inlined manifest at startup, so the region resolves its URL, OAuth client ID, and gateway the same way `us` and `eu` do.
The region picker lists the preview first and still offers US Cloud and EU Cloud, so one installer can test the PR against production data too.
An ordinary build never offers the `preview` region.

A preview build registers only its own URL scheme, so for US and EU it uses the loopback OAuth callback `http://localhost:8237/callback`, the one development builds use for every region.
If a development build can sign in to US Cloud, a preview build can too.
PostHog matches that redirect URI exactly, so the port is fixed and only one app can hold it.
Two apps that use the loopback callback, such as a development build and a preview build, must therefore sign in to US or EU one after the other.
Sign-in to the preview region itself uses the app's own scheme and has no such limit.

Readiness requires a real tester login, PKCE authorization and token exchange, an authenticated user read, desktop project access, and a gateway liveness check through the proxy.

## Implementation

- Manifest, region registry, and application identity: `packages/shared/src/desktop-preview.ts`, `regions.ts`, `urls.ts`, `oauth.ts`
- Build validation: `apps/code/scripts/preview-config.mts`
- Region guard: `packages/core/src/auth/auth.ts`
- Provisioning, gateway, and proxy: `tools/hogbox-preview/hogbox_preview/desktop_profile.py` and `stack.py`
- Lifecycle: `.github/scripts/desktop/desktop-preview-decision.js` and `.github/workflows/hogbox-preview-env.yml`
- Packaging: `.github/workflows/desktop-build-installers.yml`
