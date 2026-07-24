import type { CloudRegion } from "./regions";

export const POSTHOG_US_CLIENT_ID = "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W";
export const POSTHOG_EU_CLIENT_ID = "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9";
export const POSTHOG_DEV_CLIENT_ID = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ";

// Wildcard, not the explicit scope list: the prod OAuth apps have no seeded scope ceiling,
// so /oauth/authorize rejects the privileged llm_gateway:read with invalid_scope while "*"
// is grandfathered. Re-land the explicit list only after the US and EU app ceilings are
// seeded with ["@default", "llm_gateway:read"]. Bump OAUTH_SCOPE_VERSION on any change.
export const OAUTH_SCOPES = ["*"];

export const OAUTH_SCOPE_VERSION = 5;

// Token refresh settings
export const TOKEN_REFRESH_BUFFER_MS = 30 * 60 * 1000; // 30 minutes before expiry
export const TOKEN_REFRESH_FORCE_MS = 60 * 1000; // Force refresh when <1 min to expiry, even with active sessions

export function getOauthClientIdFromRegion(region: CloudRegion): string {
  switch (region) {
    case "us":
      return POSTHOG_US_CLIENT_ID;
    case "eu":
      return POSTHOG_EU_CLIENT_ID;
    case "dev":
      return POSTHOG_DEV_CLIENT_ID;
  }
}
