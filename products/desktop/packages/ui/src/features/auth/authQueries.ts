import type { AuthState } from "@posthog/core/auth/schemas";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import { getAuthIdentity, useAuthStore } from "./store";

export type { AuthState };
export { getAuthIdentity };

export { useAuthStateValue } from "./store";
export { useCurrentUser } from "./useCurrentUser";

function hostClient(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

function queryClient(): ImperativeQueryClient {
  return resolveService<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT);
}

export async function fetchAuthState(): Promise<AuthState> {
  return await hostClient().auth.getState.query();
}

export async function refreshAuthStateQuery(): Promise<void> {
  const state = await fetchAuthState();
  useAuthStore.getState().setAuthState(state);
}

export function clearAuthScopedQueries(): void {
  queryClient().removeQueries({
    predicate: (query) => query.meta?.authScoped === true,
  });
}
