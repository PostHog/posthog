# posthog release checks

The posthog mobile app lives in `products/desktop/apps/mobilehog`.
Its bundle ID is `com.posthog.mobilehog`.
The build workflows for `apps/mobile` target a different app.
Build and install a new native binary to update the displayed app name to `posthog`.
Keep the bundle ID and storage keys stable so updates preserve existing installations.

## Updates

The app has its own EAS project ID, but over-the-air updates remain disabled.
Store builds use the bundled JavaScript.

To enable updates, run `eas update:configure` from `products/desktop/apps/mobilehog` with access to the correct Expo organization.
Check that `extra.eas.projectId` and `updates.url` refer to that project, then set `updates.enabled` to `true`.
Build and install a new binary before publishing an update to its channel.
Do not reuse the older mobile app's project ID.

## Account changes

On iOS, Get started opens a fresh browser sign-in so users can choose a PostHog account.
The app saves the selected account's session in secure device storage and restores it on restart.
Each signed-in account has a separate query client.
Logout clears queries, task transcripts, run watchers, and composer state.
Repository selection and seen reports use storage keys scoped to the host, project, and user.
The old unscoped values are not loaded.
Appearance remains a device preference.
Late authentication results cannot restore a session after logout.
Settings > Project lists projects available to the current sign-in.
The selected project persists across restarts and token refreshes.
Switching projects clears the previous project's cached data and navigation state.
Cloud sign-in lists only projects included in the OAuth grant.

## Tasks

The drawer starts with the signed-in user's cloud tasks in the selected project, including tasks started from Desktop.
The drawer shows one task list across all spaces, without space names or space filters.
Tasks use system text, status symbols, and labeled timestamps.
All excludes archived tasks and sorts by the latest activity, as do the Running, Failed, Queued, and Done filters.
Task list options opens the archive view, where the same status filters apply.
Task lists use the server's most recent activity order and support loading older pages.
The search button opens a separate screen with its input above the keyboard.
Search matches task titles, descriptions, and task numbers on the server, across all of the user's spaces in the selected project.
Before a query, Search shows up to eight recent searches, not recent tasks. Completed searches stay on this device and are scoped to the signed-in account and project.
Local Desktop runs remain on Desktop. Archived tasks stay outside the task list.
Pull to refresh or return to the app to update tasks.

New tasks omit the channel so the server creates them in the user's personal space.
Accessible tasks owned by the user remain visible and can receive replies, regardless of their space.
The mobile app does not show space names in the drawer, search, composer, or Activity.

## Push notifications

Task completion from Desktop or mobile uses the same server-side owner notification path. Delivery requires a signed-in account, permission to show notifications, an Expo push token registered with the server, and working iOS push credentials for the app's EAS project.
The app registers after sign-in and retries when it becomes active. Notification permissions stay in iOS settings. Expo push delivery can be tested on a supported iOS simulator or a physical device; it needs a push-enabled native build.
To check cross-device delivery, start a cloud task from Desktop, put the mobile app in the background, and confirm that the completion alert arrives and opens that task. Server delivery metrics count Expo acceptance, not confirmed device delivery.

## Self-driving and task conversations

Self-driving lists actionable reports where the signed-in user is a suggested reviewer. Newest first is the default; the sort menu also offers Priority.
Opening a report marks it read for the current account and syncs with Desktop. Read actions clear the new-item indicators without dismissing the reports.
Tapping a report in the list opens a separate full-detail screen. Report actions stay in its options menu. The options menu opens the optional triage deck.
Dismiss changes the report state for the project. Activity read state is stored on the server.
Both lists support refresh and loading older items.
Read actions appear only when visible items are unread.
Empty lists have a centered explanation. Loading and request failures have separate states.
The empty Self-driving list does not show report instructions or review actions.

Task conversations keep the header and reply box outside the scrolling messages.
Conversations have no new-chat shortcut; use the drawer to start another task. The reply box has no top divider.
The + button in both composers selects up to three photos from the device library.
The composer previews selected photos, lets the user remove them, and sends images with the task message.
Image-only messages get a short prompt. Images total no more than 5 MB; unsupported iOS formats convert to JPEG.
New tasks keep the composer open until an image message is accepted, so a failed send keeps the draft.
This uses native image picker and file system modules, so install a fresh native build before testing attachments.
Images can be expanded. Saved insights and SQL references render charts or tables; unsupported insight types link to PostHog.
Mobile run requests set `X-PostHog-Client-Platform: mobile` for the PR footer.
The backend carries that value to the agent as run state. It does not change GitHub authorship or commit signing.
The Mobile footer needs the backend and agent changes to be deployed.

Before sharing a build:

- Sign in to one account in Safari, then tap Get started in the app and sign in to another account.
  Confirm that the app uses the selected account and keeps it after a restart.
  Check saved-password autofill on a device with saved PostHog credentials.
- Sign in with access to multiple projects. Open Settings > Project, search, and select another project.
  Confirm that tasks, spaces, reports, and repository choices belong to the selected project.
  Restart the app and confirm that it keeps the selected project.
- Switch projects while a token refresh or task request is pending.
  The old project must not return, and old results must not appear in the new project.
- Disconnect the network before opening the project list or selecting a project.
  Confirm that the app shows an error, keeps the current project, and permits another attempt.
- Sign in, open a task and a report, select a repository, then log out and sign in with another account.
  No data or selection from the first account should appear.
- Log out while token refresh or a task command is pending.
  The old session must not return, and the command must not start work under the new account.
- Start a cloud task in Desktop, then sign in to the same account and project on mobile.
  Confirm that Tasks shows it alongside tasks from other spaces and excludes tasks by other users.
  Open search with the sidebar button. Find a task from a different space and reply to it.
  Search for an older task by title, description text, and task number, then open a result.
  Confirm that the keyboard leaves the search field and results visible. Close search and confirm that the task list still spans all spaces.
  Load older pages. Check loading, empty, and error states. Confirm that no space names or picker appear.
- Start a task from mobile and confirm that Desktop shows it in your personal space.
  Switch projects and confirm that tasks still belong to the selected project.
- Create a task in Desktop while mobile is in the background, then return to mobile.
  Confirm that the task appears. Disconnect the network and check that refresh shows an error with Retry.
- Tap the login button twice quickly.
  Only one login flow should start.
- Open Self-driving with reports for different suggested reviewers. Only your reports should appear. Select Priority and confirm that P0 appears first.
  Open a report, mark loaded reports read, and confirm that the drawer indicator clears. Restart and check read state.
  Dismiss a report and confirm it leaves the project inbox. Disconnect the network and check that failed actions permit another attempt.
- Open Activity with no items, then with only read items. Confirm that no mark-as-read action appears.
  Mark one unread item read, then mark the remaining visible items read. Confirm that the action disappears and the badge updates.
  Load older items. New activity that arrives during a read action must remain unread.
- Open Self-driving with no reports. Confirm that the empty state has no read or triage action and no report instructions.
  Disconnect the network and refresh. Confirm that the screen shows a request error with Retry, rather than a successful empty state.
- Open a task with an uploaded image, a Markdown image, and a saved insight. Expand the images and read chart values.
  Reopen the task and check that stored attachments still load. Check an unavailable image and insight, then retry.
- Start a new task with a selected photo and text. Reply to a Desktop task with a photo but no text.
  Confirm that the agent receives each image, both conversations render it, and the picker stays available after a canceled selection.
  Remove a photo before sending and confirm that it is not sent. Try an image larger than 5 MB, then disconnect the network.
  Confirm that the draft stays available with an error rather than sending text without the image.
- In a long conversation, scroll up while the agent works. Open and close the keyboard, send a reply, and use Latest message.
  Messages must remain clear of the header and reply box, without a large blank space or forced scrolling while reading history.
- Start a task from mobile and let it create a PR. Confirm its footer says PostHog Mobile and its GitHub author is unchanged.
- Open an MCP app from a task result, enter fullscreen, then return inline.
  The content must load in each view, and app controls must still work.
- Check the login button on a device without Liquid Glass.
  Its orange background must remain visible.

Native checks need an iOS simulator or a device.
Type checks alone do not validate WebView messages, native appearance, or cloud login.

## Rich content, dictation, and report controls

- Sign out and sign in to grant insight access. Open a saved insight and a SQL chart with multiple lines.
  Open a report with attached charts. Check loading, data, unavailable content, and Retry.
- Open Mermaid flow and sequence diagrams in a stored conversation. Check light and dark appearance.
  Check an invalid diagram and Show diagram source. Diagrams must not load external content or run links.
- Open a cloud attachment after returning to an older task. Retry a failed image load and expand the image.
- In Self-driving, check all four sort orders across two pages. Open a report directly from the list.
  Start triage from the options menu. Mark loaded reports as read and confirm that unloaded reports do not change.
- Check the compact and expanded composer with the keyboard open and closed.
  Check a narrow iPhone screen, a long model name, photos, dictation, and a task that is still working.
- Dictate into a new task and an existing reply. Stop manually, then repeat and wait for silence.
  Check that each transcript appears once and stays editable before sending.
  Deny permission, cancel dictation, leave the screen, and put the app in the background.
  The microphone must stop, the existing text must remain, and the app must permit another attempt.

Dictation needs a new native build. Existing sign-ins need renewed authorization for saved insights.
The [app README](../../products/desktop/apps/mobilehog/README.md) covers setup and feature limits.

## Drafts, recovery, and review

- Write a new-task draft and a reply with a photo. Close and reopen the app. Confirm that both drafts remain in their own composers. Send one; only that draft clears.
- Switch projects and accounts with a draft open. The next account must not show it. Sign out and confirm that draft files and cached conversations are removed.
- Open tasks and Self-driving, then disconnect the network. Saved content remains readable, drafts remain editable, and Send is disabled. Reconnect; the app must not send the draft by itself.
- Interrupt a send. The draft must remain. Check for server acceptance before retrying when the result is uncertain.
- Rename, archive, and restore a task. Confirm the same state in Desktop and use each status filter. Archived running tasks must keep running.
- Mark a report read on mobile and check Desktop, then reverse the direction. Mark unread, dismiss, undo, and restore from History. Another user's read state must not change.
- Search report text and a saved message. The result must open the report or matching conversation text. Offline message search must not claim to cover all server history.
- Review a task with multiple changed files, failed checks, and a large or binary diff. Load another page and open GitHub. A task without a pull request must show an explanation.
- Use large text and VoiceOver to operate task menus, search tabs, the composer, and report actions. Check reduced motion and a narrow device in both appearances.
- Install a preview build, publish a compatible test update, and use Settings to apply it. A native-module change must produce a different fingerprint and require a new build.
- In the configured telemetry project, confirm that a test failure resolves to source code. Inspect the event payload: no prompt, image, token, search text, response body, or exception text may be present.

## Model selection and loading

- Open a running task, select another model from the same provider, and send a reply. Confirm the agent accepts the model and reasoning setting before it receives the reply.
- Reject a model change and confirm the message stays unsent and the draft stays available. Repeat with a Pi task from Desktop.
- Select different models in two tasks and a new-task draft. Move between them and confirm that each composer keeps its selection.
- Open a task, return to the list, then open it again within one minute. Confirm the conversation remains visible and the live stream is reused.
- Open a report from the list and Search. Confirm both open the full report screen, with triage available only from the Self-driving menu.
- Delay report read-state requests. Confirm loaded reports appear before those requests finish.

Deploy the report read-state migration and API, PR review endpoint, and task notification title before distributing the matching mobile build.
Mobile PR footers also require the task worker and agent image update. Existing runs can retain their previous agent image.
