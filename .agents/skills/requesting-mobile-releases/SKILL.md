---
name: requesting-mobile-releases
description: >
  Decides whether a PostHog mobile app change can ship as an over-the-air (OTA) update or needs a native
  store release, then creates the release request file under products/mobile/releases/requests/. Use
  before creating or editing a mobile release request, when asked to ship, release, publish or push an
  update of the mobile app, and when a change under products/mobile touches package.json,
  pnpm-lock.yaml, app.config.ts, eas.json, plugins/, targets/, modules/ or any expo-* or react-native-*
  dependency. Covers the native fingerprint comparison, the version rule, and what the request must say.
---

# Requesting mobile releases

A merged release request is the release trigger.
Mobile Release publishes it from `master` with no human gate.
An `ota` request goes straight to the production channel that installed apps pull from.
A `native` request submits both binaries to TestFlight and Play internal testing.
Decide the kind before you create the file, and say which kind you chose and why in the PR description.

[RELEASING.md](../../../products/mobile/docs/RELEASING.md) has the commands and the recovery procedure.
[OTA.md](../../../products/mobile/docs/OTA.md) has the runtime rules.
This skill is the decision procedure.

## 1. Classify the change

An OTA update replaces JavaScript and assets only.
The installed binary keeps its native code, so anything the native fingerprint covers forces a native release.
A change needs `native` when it touches any of:

- a dependency with native code: most `expo-*`, `react-native-*` and `@react-native-*` packages, `@shopify/react-native-skia`, and anything that ships `ios/` or `android/` directories in `node_modules`;
- `app.config.ts` fields under `ios`, `android`, `plugins`, `runtimeVersion` or `version`, and icons, splash, entitlements or permissions;
- `plugins/`, `targets/` (widgets), `modules/` (local native modules), or the build profiles in `eas.json`;
- the Expo SDK or React Native version;
- a `pnpm-lock.yaml` change that adds or bumps any of the above, also transitively.

Changes limited to `src/`, `app/` routes, assets, copy and fixtures are OTA candidates.

Quick scan from `products/mobile`:

```sh
git diff origin/master --stat -- package.json pnpm-lock.yaml app.config.ts eas.json plugins targets modules
```

An empty result means the change is probably OTA-safe.
A non-empty result does not make it native by itself. Run step 2 either way.

## 2. Confirm with the fingerprint

`pnpm release:fingerprint` prints the iOS and Android native fingerprints of the checkout, computed the same way the publisher computes them.
Compare the branch against the commit of the last completed native release:

```sh
# Find the last completed release and its native baseline commit.
TAG_SHA=$(gh api repos/PostHog/posthog/git/ref/tags/mobile-production -q .object.sha)
LAST_ID=$(gh api "repos/PostHog/posthog/git/tags/$TAG_SHA" -q .message | jq -r .id)
BASE=$(gh release view "mobile-release/$LAST_ID" --repo PostHog/posthog --json body -q .body | jq -r .native.commit)

# Head: in the branch, from products/mobile.
pnpm install --frozen-lockfile && pnpm release:fingerprint > /tmp/fp-head.json

# Base: a disposable worktree at the baseline commit.
git worktree add --detach /tmp/mobile-fp-base "$BASE"
(cd /tmp/mobile-fp-base/products/mobile && pnpm install --frozen-lockfile && pnpm release:fingerprint > /tmp/fp-base.json)
git worktree remove --force /tmp/mobile-fp-base

diff /tmp/fp-base.json /tmp/fp-head.json
```

Before the first hosted native release there is no `mobile-production` tag. Compare against `origin/master` instead, and remember that the first hosted release must be `native`.

- Identical fingerprints: the change can ship as `ota`.
- Any difference: request `native` and raise `version` in `app.config.ts`.

Compute both sides on the same machine.
Locally neither side has the EAS production environment (`GOOGLE_SERVICES_JSON`, `APPLE_TEAM_ID`), so a local fingerprint never matches the one in a receipt, but a local base-to-head comparison is valid.
The publisher repeats the comparison with the real environment after the merge and refuses an incompatible OTA. Catch it here, before the PR merges.

## 3. Apply the version rule

- `ota`: keep `version` in `app.config.ts` equal to the runtime of the last native release.
- `native`: raise `version` above it. Build numbers come from EAS (`autoIncrement`); do not set them by hand.

`pnpm release:check` enforces this against the PR base in CI.

## 4. Create the request

From `products/mobile`, with `LAST_ID` from step 2 as the predecessor:

```sh
pnpm release:request ota --id <lowercase-id> --previous "$LAST_ID" --notes "What testers should verify."
pnpm release:request native --id native-<version-digits> --previous "$LAST_ID" --notes "What changed natively."
pnpm release:check
pnpm release:test
```

Rules the publisher enforces:

- One new request per PR. A push that adds two fails.
- Requests are append-only. Never edit, rename or delete a merged request.
- Commit the request with the app change it releases.
- The notes become the body of a public GitHub prerelease. Keep customer names, credentials and internal links out of them.

Run `/running-mobile-demo-flows` on the same branch before you open the PR.

## 5. Report

State the kind, the fingerprint result per platform, the predecessor id, and the app version.
If you could not run the fingerprint comparison, say so and do not create an `ota` request.
