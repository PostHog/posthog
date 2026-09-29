import type { FetchImplementation } from "@posthog/api-client/fetcher";
import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { fetch } from "expo/fetch";
import {
  getAccessToken,
  getBaseUrl,
  getProjectId,
  refreshAccessTokenOnce,
} from "@/lib/api";

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
let clientHost: string | null = null;
let clientProjectId: number | null = null;

export function getClient(): PostHogAPIClient {
  const projectId = getProjectId();
  const host = getBaseUrl();
  if (!client || clientHost !== host) {
    client = new PostHogAPIClient(
      host,
      async () => getAccessToken(),
      () => refreshAccessTokenOnce(),
      projectId,
      {
        appVersion: "0.1.0",
        fetch: nativeFetch,
        githubConnectFrom: "posthog_mobile",
        userAgent: "posthog/mobilehog; version: 0.1.0",
      },
    );
    clientHost = host;
    clientProjectId = projectId;
  } else if (clientProjectId !== projectId) {
    client.setTeamId(projectId);
    clientProjectId = projectId;
  }
  return client;
}

export function resetClient(): void {
  client = null;
  clientHost = null;
  clientProjectId = null;
}
