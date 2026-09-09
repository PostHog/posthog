import { initTRPC, TRPCError } from "@trpc/server";
import superjson from "superjson";
import type { HostContext } from "./context";

const t = initTRPC.context<HostContext>().create({
  isServer: true,
  transformer: superjson,
});

export const router = t.router;
export const publicProcedure = t.procedure;

function hasHttpStatus(cause: unknown): cause is { status: number } {
  return (
    typeof cause === "object" &&
    cause !== null &&
    "status" in cause &&
    typeof cause.status === "number"
  );
}

const HTTP_ERROR_CODES = {
  400: "BAD_REQUEST",
  401: "UNAUTHORIZED",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  409: "CONFLICT",
} as const;

export const httpStatusProcedure = t.procedure.use(async ({ next }) => {
  const result = await next();
  if (!result.ok && result.error.code === "INTERNAL_SERVER_ERROR") {
    const cause = result.error.cause;
    if (hasHttpStatus(cause)) {
      const code =
        HTTP_ERROR_CODES[cause.status as keyof typeof HTTP_ERROR_CODES];
      if (code) throw new TRPCError({ code, cause: result.error.cause });
    }
  }
  return result;
});
export const middleware = t.middleware;
