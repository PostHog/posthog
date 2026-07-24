import type { CloudRegion } from "../types";

export const POSTHOG_US_CLIENT_ID = "a5TY7w9IjFYfes6dkPgZe6envclWw3bm2UD8ZTlm";
export const POSTHOG_EU_CLIENT_ID = "1A7vO138Fh5sYmJislicN4F5HnttI6urmFttxPDU";
export const POSTHOG_DEV_CLIENT_ID = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ";

export const OAUTH_SCOPES = [
  "user:read",
  // Required for POST /api/users/@me/push_tokens/ — without it the backend
  // rejects push-token registration with 403 and notifications never fire.
  "user:write",
  "project:read",
  "task:write",
  "integration:read",
  "conversation:write",
  "query:read",
  "llm_skill:read",
];

export const OAUTH_SCOPE_VERSION = 1;

// Token refresh settings
export const TOKEN_REFRESH_BUFFER_MS = 5 * 60 * 1000; // 5 minutes before expiry

export function getCloudUrlFromRegion(region: CloudRegion): string {
  switch (region) {
    case "us":
      return "https://us.posthog.com";
    case "eu":
      return "https://eu.posthog.com";
    case "dev":
      return "http://localhost:8010";
  }
}

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
