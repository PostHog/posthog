import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";

// Non-React accessor for the host tRPC client, for use in Zustand stores and
// subscription registrars (which run outside the React tree, so they can't use
// the `useHostTRPC` / `useHostTRPCClient` hooks). Resolves the same client the
// hooks expose from the renderer DI container.
export function hostClient(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}
