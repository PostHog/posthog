---
name: running-mobile-demo-flows
description: >
  Runs the PostHog mobile app's Argent demo flows (demo-smoke and views-smoke) on a local iOS simulator
  against a bundled Release build, and reads their results. Use before reporting a change under
  products/mobile that touches a screen, navigation, the demo fixtures, a testID, or a flow file as done,
  and when asked to smoke-test the mobile app. CI does not run these flows, so the local run is the only
  UI check a change gets.
---

# Running mobile demo flows

The flows live in `products/mobile/.argent/flows/`.
`demo-smoke` walks the inbox, a report, the hand-off sheet, decisions and chat in demo mode.
`views-smoke` covers the Views tab.
Both start and end on the sign-in screen with demo mode off, so a run can repeat right away.
[TESTING.md](../../../products/mobile/docs/TESTING.md#demo-walkthrough-on-the-ios-simulator) lists each step.

## When to run them

- A change under `products/mobile/app/`, `src/features/`, `src/ui/`, navigation, or the demo fixtures.
- A change to a flow YAML or to a `testID` the flows use.
- Before you create a release request (see `/requesting-mobile-releases`).

Skip them for a change that only touches docs, tests, backend code, or build configuration.

## Prerequisites, once per machine

- Xcode with an iOS simulator runtime, and CocoaPods. The scripts are verified on Xcode 26.6 with iOS 26.5 and on Xcode 27.1 with iOS 27.0.
- Argent 0.30.1 in a private prefix, so it does not collide with an editor's Argent server:

```sh
DO_NOT_TRACK=1 npm install --prefix /tmp/mobile-argent-tools --no-audit --no-fund @swmansion/argent@0.30.1
```

## Run the bundled flows

From `products/mobile`:

```sh
export PATH="/tmp/mobile-argent-tools/node_modules/.bin:$PATH"
export DO_NOT_TRACK=1
pnpm install --frozen-lockfile
bash scripts/ci-argent-build.sh /tmp/mobile-argent-build /tmp/mobile-argent-artifacts
bash scripts/ci-argent.sh \
    /tmp/mobile-argent-build/Build/Products/Release-iphonesimulator/PostHog.app \
    /tmp/mobile-argent-artifacts
```

Budget about 8 minutes for a fresh native build and about 3 minutes for both flows.
The build regenerates the ignored `ios/` directory, so use a disposable worktree when the checkout has manual native edits.
The flow script creates its own temporary simulator, so other booted simulators do not interfere.
Set `ARGENT_IOS_RUNTIME` to a runtime id from `xcrun simctl list runtimes` to pick another installed runtime.

## Read the result

- Exit code 0 means both flows passed.
- On failure, open `/tmp/mobile-argent-artifacts/`: the JSON report has one entry per step, failed steps have a screenshot, and `prebuild.log`, `pods.log` and `build.log` explain a native build failure.
- Both flows run even when the first fails. Report each one.
- An `idle` step can warn that a small part of the screen was still changing, such as the text caret. The next step waits for a stable element, so this warning is expected.

## Iterate on a flow with the dev client

The bundled build is slow to rebuild. While you edit a flow or a screen, use Metro instead:

1. `pnpm ios --port 8181` builds the dev client, boots a simulator and starts Metro.
2. In the dev menu, turn off **Tools button** and **Fast refresh**. The floating gear swallows taps on the inbox More button, and the refresh banner covers Back and Close.
3. Make sure demo mode is off (Settings, **Exit demo**).
4. `argent flow run demo-smoke --platform ios` from `products/mobile`. Add `--device <udid>` when more than one simulator is booted.

Known traps: a system "Open in PostHog?" alert after a deep link is invisible to Argent selectors, so dismiss it with a raw tap.
If every selector step times out with a ViewInspector RPC error, drive by normalized coordinates and screenshots instead.
[TESTING.md](../../../products/mobile/docs/TESTING.md#troubleshooting) has the rest.

## Report

State which flows ran, the Xcode and runtime versions, and pass or fail per flow.
Name the failed step and its screenshot path when one failed.
Do not commit `.argent/recordings/` or the artifact directory.
