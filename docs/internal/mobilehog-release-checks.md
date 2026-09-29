# Mobilehog release checks

Mobilehog lives in `products/desktop/apps/mobilehog`.
Its bundle ID is `com.posthog.mobilehog`.
The build workflows for `apps/mobile` target a different app.

## Updates

Over-the-air updates are disabled until the app is linked to its own EAS project.
Store builds use the bundled JavaScript.

To enable updates, run `eas init` and `eas update:configure` from `products/desktop/apps/mobilehog` with access to the correct Expo organization.
Check that `extra.eas.projectId` and `updates.url` refer to that project, then set `updates.enabled` to `true`.
Build and install a new binary before publishing an update to its channel.
Do not reuse the older mobile app's project ID.

## Account changes

Each signed-in account has a separate query client.
Logout clears queries, task transcripts, run watchers, and composer state.
Repository selection and seen reports use storage keys scoped to the host, project, and user.
The old unscoped values are not loaded.
Appearance remains a device preference.
Late authentication results cannot restore a session after logout.

Before sharing a build:

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
