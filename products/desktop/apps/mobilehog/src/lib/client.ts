import type { FetchImplementation } from "@posthog/api-client/fetcher";
import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { fetch } from "expo/fetch";
import {
  getAccessToken,
  getBaseUrl,
  getProjectId,
  refreshAccessTokenOnce,
} from "@/lib/api";
import { sessionIdentity } from "@/lib/auth";

const nativeFetch: FetchImplementation = (input, init) =>
  fetch(
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url,
    { ...init, credentials: "omit" },
  );

let client: PostHogAPIClient | null = null;
let clientIdentity: string | null = null;

export function getClient(): PostHogAPIClient {
  const identity = sessionIdentity();
  const projectId = getProjectId();
  const host = getBaseUrl();
  if (!client || clientIdentity !== identity) {
    const assertCurrent = (): void => {
      if (sessionIdentity() !== identity)
        throw new Error("Session changed. Sign in again.");
    };
    client = new PostHogAPIClient(
      host,
      async () => {
        assertCurrent();
        return getAccessToken();
      },
      async () => {
        assertCurrent();
        const token = await refreshAccessTokenOnce();
        assertCurrent();
        return token;
      },
      projectId,
      {
        appVersion: "0.1.0",
        fetch: async (input, init) => {
          assertCurrent();
          const response = await nativeFetch(input, init);
          assertCurrent();
          return response;
        },
        githubConnectFrom: "posthog_mobile",
        userAgent: "posthog/mobilehog; version: 0.1.0",
      },
    );
    clientIdentity = identity;
  }
  return client;
}

export function resetClient(): void {
  client = null;
  clientIdentity = null;
}
