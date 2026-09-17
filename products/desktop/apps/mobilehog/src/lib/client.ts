import type { FetchImplementation } from "@posthog/api-client/fetcher";
import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { fetch } from "expo/fetch";
import { getAccessToken, getBaseUrl, getProjectId } from "@/lib/api";

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
let clientProjectId: number | null = null;

export function getClient(): PostHogAPIClient {
  const projectId = getProjectId();
  if (!client) {
    client = new PostHogAPIClient(
      getBaseUrl(),
      async () => getAccessToken(),
      async () => getAccessToken(),
      projectId,
      {
        appVersion: "0.1.0",
        fetch: nativeFetch,
        githubConnectFrom: "posthog_mobile",
        userAgent: "posthog/mobilehog; version: 0.1.0",
      },
    );
    clientProjectId = projectId;
  } else if (clientProjectId !== projectId) {
    client.setTeamId(projectId);
    clientProjectId = projectId;
  }
  return client;
}

export function resetClient(): void {
  client = null;
  clientProjectId = null;
}
