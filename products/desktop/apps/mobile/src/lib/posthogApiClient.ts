import type { FetchImplementation } from "@posthog/api-client/fetcher";
import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { fetch } from "expo/fetch";
import * as Application from "expo-application";
import Constants from "expo-constants";
import { useAuthStore } from "@/features/auth";
import { refreshAccessTokenOnce } from "@/lib/api";

const MOBILE_GITHUB_CONNECT_FROM = "posthog_mobile";

let posthogApiClient: PostHogAPIClient | null = null;
let posthogApiHost: string | null = null;

const mobileFetch: FetchImplementation = (input, init) =>
  fetch(
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url,
    init,
  );

function getAppVersion(): string {
  return (
    Application.nativeApplicationVersion ??
    Constants.expoConfig?.version ??
    "unknown"
  );
}

function getAuthenticatedContext(): {
  apiHost: string;
  projectId: number;
} {
  const { cloudRegion, getCloudUrlFromRegion, projectId } =
    useAuthStore.getState();

  if (!cloudRegion) {
    throw new Error("No cloud region set");
  }
  if (!projectId) {
    throw new Error("No project ID set");
  }

  return {
    apiHost: getCloudUrlFromRegion(cloudRegion),
    projectId,
  };
}

async function getAccessToken(): Promise<string> {
  const { oauthAccessToken } = useAuthStore.getState();
  if (!oauthAccessToken) {
    throw new Error("Not authenticated");
  }
  return oauthAccessToken;
}

async function refreshAccessToken(): Promise<string> {
  await refreshAccessTokenOnce();
  return getAccessToken();
}

export function createPostHogApiClient(): PostHogAPIClient {
  const { apiHost, projectId } = getAuthenticatedContext();
  const appVersion = getAppVersion();

  return new PostHogAPIClient(
    apiHost,
    getAccessToken,
    refreshAccessToken,
    projectId,
    {
      appVersion,
      fetch: mobileFetch,
      githubConnectFrom: MOBILE_GITHUB_CONNECT_FROM,
      userAgent: `posthog/mobile.hog.dev; version: ${appVersion}`,
    },
  );
}

export function getPostHogApiClient(): PostHogAPIClient {
  const { apiHost, projectId } = getAuthenticatedContext();

  if (!posthogApiClient || posthogApiHost !== apiHost) {
    posthogApiClient = createPostHogApiClient();
    posthogApiHost = apiHost;
  } else {
    posthogApiClient.setTeamId(projectId);
  }

  return posthogApiClient;
}
