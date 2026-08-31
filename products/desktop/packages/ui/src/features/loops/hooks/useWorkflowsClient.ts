import { buildApiFetcher, createApiClient } from "@posthog/api-client";
import type { ApiClient } from "@posthog/api-client/generated";
import { getPosthogApiClientAppVersion } from "@posthog/api-client/posthog-client";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useMemo } from "react";
import { useAuthStateValue } from "../../auth/store";

export interface WorkflowsApiClient {
  client: ApiClient;
  projectId: string;
}

/**
 * The hog_flows `run` action and the create-task action's `skills` input aren't in the
 * generated OpenAPI client yet (see `@posthog/api-client/workflows`), so this builds a
 * standalone `ApiClient` the same way `useLoopsClient` does, and for the same reason — mirrors
 * that hook exactly, just under its own name so each feature's queries key off a client
 * instance scoped to it.
 */
export function useWorkflowsClient(): WorkflowsApiClient | null {
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
