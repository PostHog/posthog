# Retired mobile hosts

The legacy mobile hosts in `products/desktop/apps/mobile` and `products/desktop/apps/mobilehog` have been removed.
Their build and release instructions no longer apply.

The [proposed independent mobile app](https://github.com/PostHog/posthog/pull/118584) lives under `products/mobile` on its feature branch.
Use that proposal's README and release documentation when working on the replacement; it is not part of the desktop workspace.

Removing the legacy source does not retire installed apps or their service registrations.
Do not delete or change OAuth clients, Expo/EAS projects, signing credentials, store records, bundle identifiers, URL schemes, or notification configuration as part of this source cleanup.
Any migration of those resources needs a separate review that accounts for existing installations and the replacement app.
