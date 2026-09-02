import type { TRPCClient } from "@trpc/client";
import type { HostRouter } from "./router";

export type HostTrpcClient = TRPCClient<HostRouter>;

export const HOST_TRPC_CLIENT = Symbol.for("posthog.host.trpcClient");
