import {
  type ApiRequestMetricRecorder,
  type ApiRequestMetricRequest,
  PostHogAPIClient,
} from "@posthog/api-client/posthog-client";
import type { AuthState } from "@posthog/core/auth/schemas";
import type { HostTrpcClient } from "@posthog/host-router/client";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { getCloudUrlFromRegion, NotAuthenticatedError } from "@posthog/shared";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { recordApiRequest } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useMemo } from "react";
import { useAuthStateValue } from "./store";

export function createAuthenticatedClient(
  authState: AuthState | null | undefined,
  getValidAccessToken: () => Promise<string>,
  refreshAccessToken: () => Promise<string>,
): PostHogAPIClient | null {
  if (authState?.status !== "authenticated" || !authState.cloudRegion) {
    return null;
  }

  const client = new PostHogAPIClient(
    getCloudUrlFromRegion(authState.cloudRegion),
    getValidAccessToken,
    refreshAccessToken,
    authState.currentProjectId ?? undefined,
    { onRequestStart: recordApiRequestStart },
  );

  if (authState.currentProjectId) {
    client.setTeamId(authState.currentProjectId);
  }

  return client;
}

function recordApiRequestStart({
  method,
  path,
}: ApiRequestMetricRequest): ApiRequestMetricRecorder {
  const route = getRouterOrNull()?.state.matches.at(-1)?.routeId ?? "unknown";

  return ({ durationMs, status, outcome }) => {
    recordApiRequest(durationMs, route, method, path, status, outcome);
  };
}

function tokenAccessors(hostClient: HostTrpcClient) {
  return {
    getValidAccessToken: () =>
      hostClient.auth.getValidAccessToken.query().then((r) => r.accessToken),
    refreshAccessToken: () =>
      hostClient.auth.refreshAccessToken.mutate().then((r) => r.accessToken),
  };
}

export function useOptionalAuthenticatedClient(): PostHogAPIClient | null {
  const hostClient = useHostTRPCClient();
  const authState = useAuthStateValue((state) => state);

  return useMemo(() => {
    const { getValidAccessToken, refreshAccessToken } =
      tokenAccessors(hostClient);
    return createAuthenticatedClient(
      authState,
      getValidAccessToken,
      refreshAccessToken,
    );
  }, [
    authState.cloudRegion,
    authState.currentProjectId,
    authState.status,
    authState,
    hostClient,
  ]);
}

export function useAuthenticatedClient(): PostHogAPIClient {
  const client = useOptionalAuthenticatedClient();

  if (!client) {
    throw new NotAuthenticatedError();
  }

  return client;
}
