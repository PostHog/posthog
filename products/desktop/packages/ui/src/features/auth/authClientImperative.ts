import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { createAuthenticatedClient as createClient } from "./authClient";
import { type AuthState, fetchAuthState } from "./authQueries";

function hostClient(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

async function getValidAccessToken(): Promise<string> {
  const { accessToken } = await hostClient().auth.getValidAccessToken.query();
  return accessToken;
}

async function refreshAccessToken(): Promise<string> {
  const { accessToken } = await hostClient().auth.refreshAccessToken.mutate();
  return accessToken;
}

export function createAuthenticatedClient(
  authState: AuthState | null | undefined,
): PostHogAPIClient | null {
  return createClient(authState, getValidAccessToken, refreshAccessToken);
}

export async function getAuthenticatedClient(): Promise<PostHogAPIClient | null> {
  return createAuthenticatedClient(await fetchAuthState());
}
