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
import { ANONYMOUS_AUTH_STATE, getAuthIdentity, useAuthStore } from "./store";

export type { AuthState };
export { ANONYMOUS_AUTH_STATE, getAuthIdentity };

export { useAuthState, useAuthStateFetched, useAuthStateValue } from "./store";
export {
  AUTH_SCOPED_QUERY_META,
  authKeys,
  useCurrentUser,
} from "./useCurrentUser";

function hostClient(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

function queryClient(): ImperativeQueryClient {
  return resolveService<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT);
}

export async function fetchAuthState(): Promise<AuthState> {
  return await hostClient().auth.getState.query();
}

export function getCachedAuthState(): AuthState {
  return useAuthStore.getState().authState;
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
