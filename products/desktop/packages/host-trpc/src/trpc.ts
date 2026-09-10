import { initTRPC, TRPCError } from "@trpc/server";
import superjson from "superjson";
import type { HostContext } from "./context";

const t = initTRPC.context<HostContext>().create({
  isServer: true,
  transformer: superjson,
});

export const router = t.router;
export const publicProcedure = t.procedure.use(async ({ next }) => {
  const result = await next();
  if (!result.ok && result.error.code === "INTERNAL_SERVER_ERROR") {
    const cause = result.error.cause;
    if (cause && "status" in cause && cause.status === 400) {
      throw new TRPCError({ code: "BAD_REQUEST", cause });
    }
  }
  return result;
});
export const middleware = t.middleware;
