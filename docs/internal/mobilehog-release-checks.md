# posthog release checks

The posthog mobile app lives in `products/desktop/apps/mobilehog`.
Its bundle ID is `com.posthog.mobilehog`.
The build workflows for `apps/mobile` target a different app.
Build and install a new native binary to update the displayed app name to `posthog`.
Keep the bundle ID and storage keys stable so updates preserve existing installations.

## Updates

Over-the-air updates are disabled until the app is linked to its own EAS project.
Store builds use the bundled JavaScript.

To enable updates, run `eas init` and `eas update:configure` from `products/desktop/apps/mobilehog` with access to the correct Expo organization.
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

## Tasks and spaces

The drawer starts with the signed-in user's cloud tasks in the selected project, including tasks started from Desktop.
All tasks includes tasks by other users that the signed-in user can access.
Task lists use the server's most recent activity order and support loading older pages.
Search matches task titles, descriptions, and task numbers on the server, across spaces in the selected scope.
Local Desktop runs remain on Desktop. Archived tasks stay outside the task list.
Pull to refresh or return to the app to update tasks and spaces.

New tasks use the selected space and its server context.
The composer shows the space before sending. Tap it to search and choose an accessible space.
The default is the user's personal space. The server creates it when needed.
Space selection lasts for the current app session and clears on account or project changes.

## Inbox and task conversations

Inbox lists actionable reports where the signed-in user is a suggested reviewer, highest priority first.
Opening a report marks it read on this device. Read actions clear the new-item indicators without dismissing the reports.
Dismiss changes the report state for the project. Activity read state is stored on the server.
Both lists support refresh and loading older items.

Task conversations keep the header and reply box outside the scrolling messages.
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
  Confirm that My tasks shows it. Switch to All tasks and confirm that accessible tasks by other users appear.
  Load older pages. Search for an older task by title, description text, and task number, then open a result.
  Clear search and confirm that the normal space groups return. Check loading, empty, and error states.
- Choose a space in the new-task composer and send a message.
  Confirm that Desktop shows the task in that space. Select a private space and confirm that access stays private.
  Switch projects and confirm that the previous space selection clears.
- Create a task in Desktop while mobile is in the background, then return to mobile.
  Confirm that the task appears. Disconnect the network and check that refresh and space selection show errors with Retry.
- Tap the login button twice quickly.
  Only one login flow should start.
- Open Inbox with reports for different suggested reviewers. Only your reports should appear, with P0 first.
  Open a report, mark loaded reports read, and confirm that the drawer indicator clears. Restart and check read state.
  Dismiss a report and confirm it leaves the project inbox. Disconnect the network and check that failed actions permit another attempt.
- In Activity, mark one item read, then mark shown items read. Confirm the badge updates and older items can be loaded.
  New activity that arrives during a read action must remain unread.
- Open a task with an uploaded image, a Markdown image, and a saved insight. Expand the images and read chart values.
  Reopen the task and check that stored attachments still load. Check an unavailable image and insight, then retry.
- In a long conversation, scroll up while the agent works. Open and close the keyboard, send a reply, and use Latest message.
  Messages must remain clear of the header and reply box, without a large blank space or forced scrolling while reading history.
- Start a task from mobile and let it create a PR. Confirm its footer says PostHog Mobile and its GitHub author is unchanged.
- Open an MCP app from a task result, enter fullscreen, then return inline.
  The content must load in each view, and app controls must still work.
- Check the login button on a device without Liquid Glass.
  Its orange background must remain visible.

Native checks need an iOS simulator or a device.
Type checks alone do not validate WebView messages, native appearance, or cloud login.
