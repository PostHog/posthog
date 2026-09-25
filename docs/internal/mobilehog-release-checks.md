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
- Tap the login button twice quickly.
  Only one login flow should start.
- Open an MCP app from a task result, enter fullscreen, then return inline.
  The content must load in each view, and app controls must still work.
- Check the login button on a device without Liquid Glass.
  Its orange background must remain visible.

Native checks need an iOS simulator or a device.
Type checks alone do not validate WebView messages, native appearance, or cloud login.
