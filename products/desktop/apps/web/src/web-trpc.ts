import { resolveService } from "@posthog/di/container";
import type { HostRouter } from "@posthog/host-router/router";
import type { HostContext } from "@posthog/host-trpc/context";
import {
  createTRPCClient,
  type TRPCLink,
  unstable_localLink,
} from "@trpc/client";
import superjson from "superjson";
import { webHostRouter } from "./web-host-router";

// The ENTIRE electron->web transport difference. The renderer builds the same
// client with `links: [ipcLink()]` against the main-process router; web runs
// its slice of the host router in the SAME JS context (the backing services —
// AuthService, CloudTaskService — are host-agnostic core code), so the link is
// an in-process call, no HTTP hop. Everything downstream (HOST_TRPC_CLIENT,
// every *_CLIENT port derived from it) is identical.
//
// Context resolves services from the root container lazily per call — the
// container is registered (setRootContainer) before any procedure runs.
const localLink = unstable_localLink({
  router: webHostRouter,
  transformer: superjson,
  createContext: async (): Promise<HostContext> => ({
    container: { get: (id) => resolveService(id) },
  }),
});

export const hostTrpcClient = createTRPCClient<HostRouter>({
  // The web router is a subset of HostRouter (same procedure shapes, fewer of
  // them), so the link is cast: unimplemented procedures fail with NOT_FOUND
  // at call time instead of compile time.
  links: [localLink as unknown as TRPCLink<HostRouter>],
});
