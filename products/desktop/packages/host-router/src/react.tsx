import { createTRPCContext } from "@trpc/tanstack-react-query";
import type { HostRouter } from "./router";

export const {
  TRPCProvider: HostTRPCProvider,
  useTRPC: useHostTRPC,
  useTRPCClient: useHostTRPCClient,
} = createTRPCContext<HostRouter>();
