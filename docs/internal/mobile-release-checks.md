# Mobile app release checks

Use this checklist before sharing a build or publishing an update of the Expo + React Native app in
`products/mobile` for iOS and Android. Production native builds, store submissions and OTA updates use
[Mobile Release](../../products/mobile/docs/CI.md#mobile-release) after a release request merges to `master`.
Development and preview builds use [Mobile Build](../../products/mobile/docs/CI.md#mobile-build). Detailed instructions are in
[Releasing](../../products/mobile/docs/RELEASING.md).

## Build and update checks

- Confirm Mobile CI passes for the source commit. For production, include one native or OTA request in
  the app PR and verify the completed Mobile Release receipt identifies the tested commit and exact
  builds or update group. Native requests submit both platforms to TestFlight and Play internal testing;
  public promotion is manual. For development or preview, select the profile and platforms in Mobile Build
  and verify the resulting EAS build records that commit. The Argent demo flows run locally only and do not
  replace the manual checks below.

- Confirm the app identity and update channel. Development and preview identities have `.dev` and
  `.preview` suffixes and install alongside production.

  | Production identity | Value                     |
  | ------------------- | ------------------------- |
  | iOS bundle ID       | `com.posthog.code.mobile` |
  | Android package     | `com.posthog.mobile`      |
  | EAS project         | `@posthog/posthog`        |

  iOS updates the existing store app. Android uses a new Play record and installs separately from the
  older `com.posthog.code.mobile` app. Stop the old iOS build workflow before distributing the replacement.

- For native dependencies, config plugins or native configuration changes, raise `version` in
  `app.config.ts` and add a `native` release request. OTA requests keep the installed runtime version and
  require a completed hosted native baseline. The runtime follows the app version; the hosted publisher
  also checks native fingerprints and production environment inputs. See
  [OTA updates](../../products/mobile/docs/OTA.md) for compatibility and validation checks.
- Production OTA promotion reaches every compatible production-channel build, including TestFlight and
  public-store builds; there is no separate TestFlight OTA audience or tester approval gate. Verify the
  change before merge, then check the receipt and compatible-device behavior after publication.
- Confirm the matching backend APIs and OAuth scopes are available on the target host. Check
  [known gaps](../../products/mobile/docs/GAPS.md) before treating an unavailable feature as a regression.
- Run the [demo walkthrough](../../products/mobile/docs/TESTING.md#demo-walkthrough-on-the-ios-simulator),
  then test the actual build with a real account on each platform being shared. A web preview or passing
  typecheck does not verify native sign-in, push delivery or the widget.

## Manual smoke checks

- **Sign-in and account boundaries.** Sign in, restart and confirm the session restores. Switch projects
  and verify reports, chats and Views change together. Sign out and use another account; previous data,
  drafts and selections must not appear. Check canceled sign-in and an expired session.
- **Inbox and reports.** Refresh and load older reports, open one and check its evidence and read state.
  Resolve, dismiss and undo an action; confirm the result on the web. Start PostHog work and answer an
  agent question. Check external handoff and Copy prompt; preparing a prompt must leave report state unchanged.
- **Chats.** Start a chat, reopen it from Chats, and continue a report discussion. Send text and an
  attachment, check streamed replies and an agent question, and open a PR link. Queue a message while the
  agent works. Reopen an unsent draft after restarting; a failed send must keep it. In a long conversation,
  scrolling back and opening the keyboard must leave messages and the composer usable.
- **Views.** Open a dashboard, saved insight and web analytics. Change a date range and pull to refresh.
  Pin and unpin a view, then confirm its star on the web. Check loading, empty, unavailable and retry states.
- **Notifications.** Use a physical device with working APNs or FCM credentials. Start or actively continue
  a task from mobile, background the app, and check its notification opens the correct chat. Test a report
  push and a tap after a cold start. Ordinary task alerts use the title "PostHog"; report alerts can have
  report-specific titles. Check the master and category controls in Settings, foreground suppression for
  the open chat, and a local snooze reminder. Report pushes also need `posthog-code-mobile-push`.
  See [Push notifications](../../products/mobile/docs/PUSH.md) for setup and routing checks.
- **Recovery and appearance.** Disconnect during refresh or send, then reconnect. Show a retryable error,
  preserve the draft and avoid duplicate sends. Check light and dark appearance, a narrow supported phone,
  larger text and screen-reader labels on the main actions.
- **Hedgehog widget.** Install a fresh native build. Check small and medium iOS widgets and Android resizing:
  the garden fills the widget, the hedgehog stays visible through walks and jumps, and taps change character
  without resetting its position. Confirm the selection survives an app launch and refresh. Check iOS
  Reduce Motion and the fallback before the app's first launch.
  See the [widget guide](../../products/mobile/modules/hedgehog-widget/README.md).

## Record the result

Record the commit, app version and build number or update ID, platforms/devices checked, and any failures
or checks not run in the release notes or PR. Before store release, repeat the core sign-in, report, chat
and notification checks on the TestFlight and Play internal builds.
