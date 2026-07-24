import type { CloudTaskService } from "@posthog/core/cloud-task/cloud-task";
import { CLOUD_TASK_SERVICE } from "@posthog/core/cloud-task/identifiers";
import {
  CloudTaskEvent,
  designateRelayedMcpServersInput,
  onUpdateInput,
  retryInput,
  sendCommandInput,
  sendCommandOutput,
  stopInput,
  stopOutput,
  unwatchInput,
  watchInput,
} from "@posthog/core/cloud-task/schemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const cloudTaskRouter = router({
  watch: publicProcedure
    .input(watchInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<CloudTaskService>(CLOUD_TASK_SERVICE).watch(input),
    ),

  unwatch: publicProcedure
    .input(unwatchInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<CloudTaskService>(CLOUD_TASK_SERVICE)
        .unwatch(input.taskId, input.runId),
    ),

  retry: publicProcedure
    .input(retryInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<CloudTaskService>(CLOUD_TASK_SERVICE)
        .retry(input.taskId, input.runId),
    ),

  designateRelayedMcpServers: publicProcedure
    .input(designateRelayedMcpServersInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<CloudTaskService>(CLOUD_TASK_SERVICE)
        .designateRelayedMcpServers(input.runId, input.servers),
    ),

  sendCommand: publicProcedure
    .input(sendCommandInput)
    .output(sendCommandOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<CloudTaskService>(CLOUD_TASK_SERVICE)
        .sendCommand(input),
    ),

  stop: publicProcedure
    .input(stopInput)
    .output(stopOutput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<CloudTaskService>(CLOUD_TASK_SERVICE).stop(input),
    ),

  onUpdate: publicProcedure
    .input(onUpdateInput)
    .subscription(async function* (opts) {
      const service =
        opts.ctx.container.get<CloudTaskService>(CLOUD_TASK_SERVICE);
      try {
        for await (const data of service.toIterable(CloudTaskEvent.Update, {
          signal: opts.signal,
        })) {
          if (
            data.taskId === opts.input.taskId &&
            data.runId === opts.input.runId
          ) {
            yield data;
          }
        }
      } finally {
        service.unwatch(opts.input.taskId, opts.input.runId);
      }
    }),
});
