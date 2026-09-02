// GitHub's per-installation settings page for an org install is owner-only and
// 404s for members, so org installs point at the app page, which loads for
// anyone (owners get Configure, members get request access).
export const POSTHOG_GITHUB_APP_URL = "https://github.com/apps/posthog";
