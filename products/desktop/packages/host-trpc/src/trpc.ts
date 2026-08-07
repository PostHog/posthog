import { initTRPC } from "@trpc/server";
import superjson from "superjson";
import type { HostContext } from "./context";

const t = initTRPC.context<HostContext>().create({
  isServer: true,
  transformer: superjson,
});

export const router = t.router;
export const publicProcedure = t.procedure;
export const middleware = t.middleware;
export const mergeRouters = t.mergeRouters;
