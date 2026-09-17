import { buildApiFetcher, createApiClient } from "@posthog/api-client";
import type { ApiClient } from "@posthog/api-client/generated";
import { getPosthogApiClientAppVersion } from "@posthog/api-client/posthog-client";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useMemo } from "react";
import { useAuthStateValue } from "../../auth/store";

export interface LoopsApiClient {
  client: ApiClient;
  projectId: string;
}

/**
 * `PostHogAPIClient` has no wrapper methods for the workflow calls behind
 * loops and its underlying `ApiClient` is private. This builds a standalone
 * `ApiClient` the same way `PostHogAPIClient`'s constructor does, so
 * `@posthog/api-client/hogFlowLoops` has something to call against.
 */
export function useLoopsClient(): LoopsApiClient | null {
  const hostClient = useHostTRPCClient();
  const authState = useAuthStateValue((state) => state);

  return useMemo(() => {
    if (authState.status !== "authenticated" || !authState.cloudRegion) {
      return null;
    }
    if (authState.currentProjectId == null) {
      return null;
    }

    const baseUrl = getCloudUrlFromRegion(authState.cloudRegion);
    const client = createApiClient(
      buildApiFetcher({
        getAccessToken: () =>
          hostClient.auth.getValidAccessToken
            .query()
            .then((r) => r.accessToken),
        refreshAccessToken: () =>
          hostClient.auth.refreshAccessToken
            .mutate()
            .then((r) => r.accessToken),
        appVersion: getPosthogApiClientAppVersion(),
      }),
      baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl,
    );

    return { client, projectId: String(authState.currentProjectId) };
  }, [authState, hostClient]);
}
