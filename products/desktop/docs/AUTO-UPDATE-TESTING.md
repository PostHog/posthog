# Testing Auto-Update Locally

This explains how to exercise the real auto-update flow (check, download, install, relaunch) on your own machine, against a local feed, without cutting a GitHub release. For how releases and versioning actually work in production, see [UPDATES.md](./UPDATES.md).

The same harness runs nightly in CI (`.github/workflows/code-update-e2e.yml`) on a signed macOS build.

## What this covers

Auto-update is macOS and Windows only (`isSupported` in `apps/code/src/main/platform-adapters/electron-updater.ts`). This guide is macOS, which is where the harness and the nightly job run.

The flow under test: a packaged old build checks a local feed, downloads a newer build, and Squirrel.Mac swaps the app bundle in place and relaunches into the new version.

Two legs run against the same `2.0.0` feed:

- **electron-builder to electron-builder**: the forward-compatibility baseline. A `1.0.0` electron-builder build updates to the `2.0.0` electron-builder build using `electron-updater`.
- **Forge to electron-builder**: a real Electron Forge build (the last Forge release, `v0.55.132`) updates to the `2.0.0` electron-builder build using the genuine built-in Squirrel.Mac client. This is the case real users are in: their app was made by Forge, and we need it to pick up the electron-builder builds we ship now. See [The Forge to electron-builder leg](#the-forge-to-electron-builder-leg).

## What you need

- A packaged build (not `pnpm dev`). Auto-update only runs when `app.isPackaged` is true.
- For the full install and relaunch: a Developer ID signing identity. Squirrel.Mac only swaps a bundle whose signature matches the running app's designated requirement, so both builds must be signed with the same identity. Set `CSC_LINK` / `CSC_KEY_PASSWORD`, or have a Developer ID cert in your login keychain.
  - Without a matching identity you can still watch check, available, download and ready, but the final swap needs the signature. If you can't sign locally, skip the local build and pull the CI-signed pair instead (see below).
- Notarization is intentionally skipped (`SKIP_NOTARIZE=1`). It is a Gatekeeper concern for first launch of a downloaded app, not what the in-place update verifies, and a locally built bundle carries no quarantine attribute.

## The harness

| Piece | Role |
| --- | --- |
| `apps/code/scripts/dev-update/build-pair.sh` | Builds a signed `2.0.0` feed plus a runnable signed `1.0.0` app (the baseline leg) |
| `apps/code/scripts/dev-update/build-old-forge.sh` | Builds the last Forge release (`v0.55.132`) as the signed `1.0.0` old app for the Forge leg |
| `apps/code/scripts/dev-update/serve.mjs` | Dependency-free, range-capable static server. Serves the `electron-updater` manifest AND the Squirrel.Mac JSON feed the built-in updater expects |
| `apps/code/tests/e2e/tests/update.spec.ts` | Baseline leg: drive `electron-updater` download and install, then assert the swap and relaunch |
| `apps/code/tests/e2e/tests/update-forge.spec.ts` | Forge leg: let the old build's built-in Squirrel.Mac client download, drive install, then assert the swap and relaunch |
| `POSTHOG_E2E_UPDATE_FEED` env | Baseline leg: when set, `electron-updater` points at this URL instead of GitHub (gated, inert in production) |
| `POSTHOG_E2E_UPDATE_HOST` env | Forge leg: the one-line env seam baked into the old build so its built-in updater asks this host instead of `update.electronjs.org` |
| `apps/code/tests/e2e/playwright.update.config.ts`, `playwright.update-forge.config.ts` | Dedicated Playwright configs; the only place each update spec runs |
| `globalThis.__e2eUpdates` | Baseline leg only: set in the main process when `POSTHOG_E2E_UPDATE_FEED` is present; lets the test drive `check` / `download` / `install` / `status` |

## Build the pair locally

```bash
bash apps/code/scripts/dev-update/build-pair.sh
```

This runs `electron-vite build` once, then builds twice with `electron-builder`:

- The new `2.0.0` artifacts are copied to `apps/code/out/dev-update-feed/` (`latest-mac.yml`, the zip and its blockmap). This is the feed.
- The old `1.0.0` app is left at `apps/code/out/mac-arm64/PostHog.app`. This is what you run.

Override the versions if you want (`2.0.0` must be greater than `1.0.0`):

```bash
OLD_VERSION=1.0.0 NEW_VERSION=2.0.0 bash apps/code/scripts/dev-update/build-pair.sh
```

This takes a few minutes and may prompt for keychain access to sign.

## Or: one command, against the CI-signed pair (no local signing)

If you don't have a Developer ID cert, `build-pair.sh` produces unsigned builds and the swap won't complete. Instead run one script: it pulls the signed pair from the latest green run, serves the feed, and opens the old app pointed at it. Squirrel verifies signatures cryptographically (it does not need the cert in your keychain), so the CI-signed pair updates locally just like a real release.

```bash
bash apps/code/scripts/dev-update/run-from-ci.sh
# a specific run:         bash apps/code/scripts/dev-update/run-from-ci.sh <run-id>
# automated spec instead: AUTOMATED=1 bash apps/code/scripts/dev-update/run-from-ci.sh
```

Needs the GitHub CLI (`gh`) authenticated, and the installed PostHog app must be quit (the test build shares its single-instance lock and data dir). The app opens on `1.0.0` with an update available; click Download, then Restart, and it swaps and relaunches into `2.0.0`.

## 2a. Run it automated (Playwright)

The spec starts its own feed server, copies the `1.0.0` app to a disposable run dir (so a rerun starts clean), drives the full flow and asserts the relaunched app is `2.0.0`.

```bash
pnpm --filter code exec playwright test \
  --config=tests/e2e/playwright.update.config.ts
```

The spec runs only through this dedicated config. The general e2e suite excludes it by path (`testIgnore` in `playwright.config.ts`), so it never runs there without a feed.

## 2b. Run it manually (real UI)

Serve the feed in one terminal:

```bash
node apps/code/scripts/dev-update/serve.mjs apps/code/out/dev-update-feed 8788
```

Launch the `1.0.0` app pointed at it in another terminal:

```bash
POSTHOG_E2E_UPDATE_FEED=http://127.0.0.1:8788 \
  "apps/code/out/mac-arm64/PostHog.app/Contents/MacOS/PostHog"
```

The app checks on launch and the update banner shows `2.0.0` is available. Open it, click Download, watch progress, then Restart. The app quits, swaps and relaunches into `2.0.0`.

A manual run swaps `out/mac-arm64` in place, so rerun `build-pair.sh` (or just the old build) to reset to `1.0.0` before testing again.

## Verifying the result

- Running version: open the in-app About, or read the bundle:
  ```bash
  plutil -extract CFBundleShortVersionString raw \
    "apps/code/out/mac-arm64/PostHog.app/Contents/Info.plist"
  ```
- Update logs are in the main log:
  ```bash
  tail -f ~/.posthog-code/logs/main.log
  ```

## The Forge to electron-builder leg

The baseline leg proves an electron-builder build updates to a newer electron-builder build. That is the future. It does not prove what every current user needs: their app was made by Electron Forge and runs the genuine built-in Squirrel.Mac client, not `electron-updater`. This leg covers that.

### What it proves

A real Forge build picks up an electron-builder build through its own updater, end to end: boot on the Forge `1.0.0`, the built-in client checks the local feed, downloads the `2.0.0` electron-builder zip, Squirrel.Mac swaps the bundle in place, relaunches, and the fresh launch is `2.0.0`. The swap only happens if the new bundle's code signature satisfies the running app's designated requirement, so signing parity is part of what is verified.

### How the old build is produced

`build-old-forge.sh` checks the last Forge release out into an isolated git worktree and builds it there, so the current branch checkout is untouched. The pinned commit is `cb0ca68db` (`v0.55.132`), the last release before the electron-builder migration. Override with `OLD_FORGE_REF` if needed.

It is a genuine `electron-forge package` build, not a rebuild with electron-builder, because the whole point is the built-in Squirrel.Mac client that shipped to users. It is signed with the same identity the new build uses (Forge resolves the identity by name from a keychain, so the script imports `CSC_LINK` into a temp keychain and derives `APPLE_CODESIGN_IDENTITY`). Both Forge and electron-builder use bundle id `com.posthog.array`, so the designated requirements match and the swap is allowed.

### Two seams the old build needs

- **Feed host (`POSTHOG_E2E_UPDATE_HOST`)**: a one-line change applied in the worktree so the built-in updater's feed host honours the env var instead of being hardcoded to `update.electronjs.org`. Nothing in the download, verify or swap path changes. At test time the app's own boot check then drives the real download against the local feed, exactly as it would against `update.electronjs.org` in production.
- **Local networking (ATS)**: the built-in updater uses `NSURLSession`, which enforces App Transport Security, so plain http to loopback is blocked by default. The script adds `NSAppTransportSecurity.NSAllowsLocalNetworking` to the packaged `Info.plist` and re-signs the bundle with the same identity and entitlements, so the designated requirement is unchanged. `electron-updater` (the baseline leg) uses its own Node HTTP client and is not subject to ATS, which is why only this leg needs it.

`serve.mjs` answers the Squirrel.Mac feed shape (`GET /<owner>/<repo>/darwin-<arch>/<version>` returns `204` when current, or `200` + `{ url }` pointing at the new zip) in addition to the static `electron-updater` manifest. It self-configures from the feed's `latest-mac.yml`, so the same feed dir drives both legs.

### Run it locally

You need the same Developer ID signing setup as the baseline leg (`CSC_LINK` / `CSC_KEY_PASSWORD`, or an identity in a keychain), full git history, and the `2.0.0` feed from `build-pair.sh`:

```bash
bash apps/code/scripts/dev-update/build-pair.sh        # the 2.0.0 feed
bash apps/code/scripts/dev-update/build-old-forge.sh   # the old Forge 1.0.0 app
pnpm --filter code exec playwright test \
  --config=tests/e2e/playwright.update-forge.config.ts
```

The old Forge app lands at `apps/code/out/old-forge/PostHog Code.app`. The spec copies it to a disposable run dir, so a rerun starts from `1.0.0` again without rebuilding.

### Or: against the CI-signed Forge build (no local signing, no 9-minute build)

The Forge counterpart to `run-from-ci.sh`. It pulls the CI-signed Forge `1.0.0` app and the `2.0.0` feed from the latest green run, verifies the signature survived transport, serves the feed, and launches the Forge app so its built-in Squirrel.Mac client drives the real update:

```bash
bash apps/code/scripts/dev-update/run-from-ci-forge.sh
# a specific run:         bash apps/code/scripts/dev-update/run-from-ci-forge.sh <run-id>
# automated spec instead: AUTOMATED=1 bash apps/code/scripts/dev-update/run-from-ci-forge.sh
```

Needs `gh` authenticated and the installed PostHog app quit. The CI job uploads the Forge app as a `ditto` zip (`update-old-forge-build-1.0.0`) so its symlinks and code signature survive the artifact round-trip; a plain directory upload would break both and the swap would fail.

## CI

`code-update-e2e.yml` runs both specs nightly on `macos-15` with the real signing secrets, and on demand:

```bash
gh workflow run "Code Update E2E (macOS)"
```

It builds the `2.0.0` feed and the baseline `1.0.0` app, runs the baseline spec via `playwright.update.config.ts`, then builds the old Forge `1.0.0` app and runs the Forge spec via `playwright.update-forge.config.ts`. Each leg asserts exactly one test actually ran, so a missing feed or a silent skip fails the job. The Forge leg runs after the baseline so a flake in the (riskier) old-build step can never mask the baseline result.

Every run renders a proof summary per leg on the run page and uploads, on pass or fail: both proof manifests, main log and Squirrel ShipIt cache (artifact `update-e2e-macos`), plus the signed builds as their own artifacts (`update-old-build-1.0.0`, `update-new-build-2.0.0`, `update-old-forge-build-1.0.0`) you can pull as shown above.

## Cleanup

```bash
rm -rf apps/code/out/dev-update-feed apps/code/out/e2e-update-run
```
