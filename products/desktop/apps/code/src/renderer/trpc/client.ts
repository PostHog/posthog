import { ipcInstrumentationLink } from "@features/dev-toolbar/ipcInstrumentationLink";
import { ipcLink } from "@posthog/electron-trpc/renderer";
import type { HostRouter } from "@posthog/host-router/router";
import { createTRPCClient } from "@trpc/client";
import {
  createTRPCContext,
  createTRPCOptionsProxy,
} from "@trpc/tanstack-react-query";
import { queryClient } from "@utils/queryClient";
import superjson from "superjson";
import type { TrpcRouter } from "../../main/trpc/router";

export const trpcClient = createTRPCClient<TrpcRouter>({
  links: [
    ipcInstrumentationLink<TrpcRouter>(),
    ipcLink({ transformer: superjson }),
  ],
});

export const hostTrpcClient = createTRPCClient<HostRouter>({
  links: [ipcLink({ transformer: superjson })],
});

const context = createTRPCContext<TrpcRouter>();
export const TRPCProvider = context.TRPCProvider;
export const useTRPC = context.useTRPC;

export const trpc = createTRPCOptionsProxy<TrpcRouter>({
  client: trpcClient,
  queryClient,
});
