import type { HandoffService } from "@posthog/core/handoff/handoff";
import { HANDOFF_SERVICE } from "@posthog/core/handoff/identifiers";
import {
  HandoffEvent,
  handoffExecuteInput,
  handoffExecuteResult,
  handoffPreflightInput,
  handoffPreflightResult,
  handoffToCloudExecuteInput,
  handoffToCloudExecuteResult,
  handoffToCloudPreflightInput,
  handoffToCloudPreflightResult,
} from "@posthog/core/handoff/schemas";
import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

const getService = (container: ServiceResolver) =>
  container.get<HandoffService>(HANDOFF_SERVICE);

export const handoffRouter = router({
  preflight: publicProcedure
    .input(handoffPreflightInput)
    .output(handoffPreflightResult)
    .query(({ ctx, input }) => getService(ctx.container).preflight(input)),

  execute: publicProcedure
    .input(handoffExecuteInput)
    .output(handoffExecuteResult)
    .mutation(({ ctx, input }) => getService(ctx.container).execute(input)),

  preflightToCloud: publicProcedure
    .input(handoffToCloudPreflightInput)
    .output(handoffToCloudPreflightResult)
    .query(({ ctx, input }) =>
      getService(ctx.container).preflightToCloud(input),
    ),

  executeToCloud: publicProcedure
    .input(handoffToCloudExecuteInput)
    .output(handoffToCloudExecuteResult)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).executeToCloud(input),
    ),

  onProgress: publicProcedure
    .input(z.object({ taskId: z.string() }))
    .subscription(async function* (opts) {
      const service = getService(opts.ctx.container);
      for await (const data of service.toIterable(HandoffEvent.Progress, {
        signal: opts.signal,
      })) {
        if (data.taskId === opts.input.taskId) {
          yield data;
        }
      }
    }),
});
