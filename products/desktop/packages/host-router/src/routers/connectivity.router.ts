import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  type ConnectivityStatusOutput,
  connectivityStatusOutput,
} from "@posthog/workspace-server/services/connectivity/schemas";
import {
  CONNECTIVITY_CLIENT,
  type HostConnectivityClient,
} from "../ports/connectivity-client";

const ws = (container: ServiceResolver) =>
  container.get<HostConnectivityClient>(CONNECTIVITY_CLIENT);

export const connectivityRouter = router({
  getStatus: publicProcedure
    .output(connectivityStatusOutput)
    .query(({ ctx }) => ws(ctx.container).getStatus()),

  checkNow: publicProcedure
    .output(connectivityStatusOutput)
    .mutation(({ ctx }) => ws(ctx.container).checkNow()),

  onStatusChange: publicProcedure.subscription(async function* (opts) {
    const queue: ConnectivityStatusOutput[] = [];
    let resolve: (() => void) | null = null;
    const unsubscribe = ws(opts.ctx.container).onStatusChange((status) => {
      queue.push(status);
      resolve?.();
    });
    try {
      while (!opts.signal?.aborted) {
        if (queue.length === 0) {
          await new Promise<void>((r) => {
            resolve = r;
          });
          resolve = null;
        }
        while (queue.length > 0) {
          yield queue.shift() as ConnectivityStatusOutput;
        }
      }
    } finally {
      unsubscribe();
    }
  }),
});
