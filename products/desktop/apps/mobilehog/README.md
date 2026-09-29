# PostHog mobile

The iOS app lets you start and continue cloud tasks, review Self-driving reports, and read task activity.
It uses the same account and project data as [PostHog Desktop](https://posthog.com/docs/posthog-desktop/tasks).
The installed app name is `posthog`. The package, Expo project, and bundle ID still use `mobilehog`.

## Install a development build

Use a Mac with Xcode, an iOS simulator or connected iPhone, Node.js, and the repository's pnpm version.
From the repository root:

```bash
cd products/desktop
pnpm install
pnpm --filter @posthog/mobilehog prebuild --platform ios
pnpm --filter @posthog/mobilehog ios --device
```

Select your iPhone when prompted. Omit `--device` for the simulator.
Xcode must have a signing team and a provisioning profile for `com.posthog.mobilehog` when you use a phone.

After the first build, start Metro with:

```bash
pnpm --filter @posthog/mobilehog start:clear
```

Rebuild after changes to native dependencies, permissions, or the app name.
Expo Go cannot run this app's native modules.

## Install a preview build

Use an Expo account with access to the PostHog EAS project and its Apple signing credentials.
From `products/desktop/apps/mobilehog`:

```bash
pnpm dlx eas-cli build --platform ios --profile preview
```

Follow EAS prompts to register your device, then install the build from its link.
Preview builds do not need Metro. Install a new native build once to enable compatible updates.
After that, **Settings → App → Check for updates** can download a published update and restart the app when you choose.
Updates use the build channel and a native fingerprint. Changes to native modules or permissions still need a new build.
The production profile is for distribution through Apple; it does not install directly from an EAS link.

The older app in `apps/mobile` has a different bundle ID, `com.posthog.code.mobile`.
Both apps register `posthog://`. If both are installed, iOS can send sign-in and task links to the wrong app.
Remove the older app if this occurs. This deletes that app's local data.

## Sign in and choose a project

Choose your cloud region, then select **Get started**.
Sign-in opens a fresh browser session so you can choose an account. The app stores the session in the device's secure storage.
Use **Settings → Project** to select another authorized project. Sign out to change accounts.

Saved insights require `insight:read`, and live charts require `query:read`.
If you signed in before the insight permission was added, sign out and sign in again to grant it.
The app cannot use permissions that your account or project does not have.

## Tasks and chat

- **Recent Tasks** lists your cloud tasks in the selected project, across all spaces. Pull to refresh or return to the app to load changes.
- Use **Search** for task titles and descriptions, Self-driving report titles and summaries, or messages saved on this phone. Message search covers up to 20 opened conversations, not all server history. Select a result to open the matching message. Before you enter text, Search shows recent searches.
- Model and reasoning selections apply to the next message. The app waits for the agent to accept them before it sends your message. If a change fails, the draft stays on the phone. A live Claude Code or Codex run can change models within its provider; use **Task options → Stop run** before changing providers. Pi runs can change providers.
- Start a task from the main menu. Select a repository and model, then send your request.
- New tasks use the server's Personal default. Mobile does not show space controls or labels.
- Open an existing task to read it and send replies. Tasks from Desktop must use cloud runs and remain accessible to your account.
- Use the Recent Tasks menu to filter by status or open Archived. The task menu can rename, archive, or restore a task. Archiving does not stop a running task.
- Select **+** to attach photos. You can send text, photos, or both. Remove a preview before sending to exclude that photo.
- Select the microphone to dictate. Select Stop or wait for recognition to finish. Edit the resulting text, then select Send.
- While the agent works, you can read earlier messages. Select **Latest message** to return to the end.

Photo attachments support JPEG, PNG, GIF, and WebP. iOS converts HEIC selections to JPEG.
You can attach up to three photos, with a combined size below 5 MB. Text and photo drafts survive app restarts.
Drafts are scoped to the account, project, and task. They expire after seven days without edits. Signing out removes drafts and cached conversations.
When offline, you can read saved content and edit drafts. Send is disabled until the connection returns. Failed sends keep the draft; the app does not resend it automatically.
If a request reached the server but its response was lost, check Recent Tasks or the conversation before sending again.

Dictation uses the device's speech recognition service with English (`en-US`).
It requests microphone and speech recognition permission when you first use it.
It uses on-device recognition when the device supports it; otherwise the system service can use the network.
The task receives text, not an audio recording. Dictation stops when you leave the screen or put the app in the background.
This is speech-to-text input, not a voice conversation with the agent.

## Self-driving

The list shows actionable reports for which you are a suggested reviewer.
Select a report to open its full details on a separate screen. The report options menu contains task and report actions. Opening it marks it as read for your account.

Use the sort control to choose **Newest first**, **Oldest first**, **Priority**, or **Recently updated**.
Sorting applies on the server, including reports you have not loaded yet. Newest first is the default.
Use **Load more** to read older pages.

The **⋯** menu contains **Triage reports** and a counted action to mark loaded reports as read.
Triage is optional. It lets you review reports one at a time and dismiss them or start a task.
The read action asks for confirmation and leaves reports in the list. It does not dismiss them.
Read state syncs with Desktop when both apps and the backend include the read-state API. The phone keeps up to 500 local indicators for offline use. Failed sync does not hide loaded reports.
The menu also contains Unread and History views. History contains dismissed and resolved reports. Mark unread keeps a report for later.
Dismissal changes the report for the project and can close its pull request. Undo restores the report; it does not reopen a closed pull request.

## Review a result

Open a task, then **⋯ → Review result** to read its pull request summary, check result, and changed files.
Expand a file to read the diff. Large and binary changes must open in GitHub. Review requires the task's GitHub integration and the new backend endpoint.
The review is read-only; use **Open in GitHub** for approvals, comments, or merging. Pull to refresh before acting on a check result.

## Activity

Activity shows task updates and replies. Unread items have a marker and stronger text.
Open an item to read its task, or use its read action. The bulk action shows how many loaded updates it will change.
New updates remain unread. Activity read state is stored on the server.

## Images, charts, and diagrams

Chat displays inline images, uploaded cloud attachments, saved insight references, and SQL charts.
Tap an image to expand it. If an image or chart fails to load, tap Retry.
Report details also display the charts attached to the report.

Supported charts include trend lines, bars, funnel steps, tables, and single values.
Some visualizations, including retention and path views, must open in PostHog.
Images must have a supported image URL or a cloud attachment reference. A file that exists only on another computer is not available on the phone.
Expired or deleted content, and content outside your project access, can remain unavailable after a retry.

Mermaid code blocks render as diagrams. The renderer ships with the app and does not send diagram text to a public rendering service.
Use **Show diagram source** to read the code. Invalid diagrams show an error and a retry action.
Diagram links, scripts, and external resources are disabled.

## Notifications and other limits

Push registration runs automatically after sign-in and when the app becomes active.
Allow notifications in iOS Settings. A preview build can receive push notifications.
Delivery also needs a registered Expo token, valid Apple push credentials, the server notification flag, and a successful backend send.
Test with the app in the background and a cloud task owned by the same account. Desktop task completion can notify the phone too.
There is no notification diagnostic control in the app. Registration failures go to developer logs without device tokens.

This app is iOS-first. Android and browser builds are not supported release targets.
It needs network access to send tasks or refresh reports. Saved lists and message text remain available offline; image and chart caches are not guaranteed. It does not run local repositories, local tasks, or worktrees on the phone.
Mobile-created runs request a **Created with PostHog Mobile** PR footer; this requires the matching backend and agent deployment.
This does not change the GitHub author or commit signature.

Recently opened tasks reuse their live connection for up to one minute after you leave. The app keeps at most two inactive connections.
Cached tasks, reports, repository choices, and model choices appear while the app refreshes them. Signing out or switching projects closes the connections and clears the in-memory cache.

## Backend deployment

Installing the mobile app does not deploy the server changes in this PR.
The matching server release must include the report read-state API and database migration, the task PR review endpoint, and the task push title (`posthog`).
The task worker and agent image must also include the Mobile PR footer support. New runs use that image; existing runs can keep the previous image.
Deploy the server changes before distributing a build that uses the new endpoints. No manual device-token changes are required.

## Release and diagnostics

Copy `.env.example` to `.env` for the shared PostHog telemetry destination. Configure the same `EXPO_PUBLIC_POSTHOG_API_KEY` and `EXPO_PUBLIC_POSTHOG_HOST` in EAS before a release build.
Without those values, telemetry is disabled. The SDK records send outcomes, connection failures, and JavaScript errors. It excludes prompts, search text, photos, tokens, response bodies, and exception text. Session Replay is disabled.

The PostHog Expo and Metro plugins add source-map support. Native upload hooks are enabled only when `POSTHOG_CLI_TOKEN` is present during prebuild, so local builds do not need upload credentials. Install `posthog-cli` on the build worker and set its `POSTHOG_CLI_TOKEN`, `POSTHOG_CLI_ENV_ID`, and `POSTHOG_CLI_HOST` through build secrets for uploads. Never put the CLI token in an `EXPO_PUBLIC_` variable.
Native crashes and native symbol uploads are not enabled. Validate source-map resolution in the release project before distribution.

Publish an update only after release checks, first on the preview channel. The installed build must have the same native fingerprint. Do not publish private test fixtures or user screenshots.

## Use a local backend

Cloud sign-in is the normal path. Local sign-in is for development only.
In the repository's local environment, set `ALLOW_DEV_API_KEY_REVEAL=1` and `SANDBOX_PROVIDER=docker` in `.env`.
Run `python manage.py setup_local_api_key` in the repository's Python environment, then restart the stack.

`src/config.ts` defines the local backend and MCP addresses.
Use your Mac's LAN address instead of `localhost` for a real phone.
Never enable local API key reveal on a shared or production backend.

Before sharing a build, complete the [mobile release checks](../../../../docs/internal/mobilehog-release-checks.md).
