import {
  channelTaskRecordSchema,
  fileChannelTaskInput,
  listChannelTasksInput,
  unfileChannelTaskInput,
} from "@posthog/core/canvas/channelTaskSchemas";
import { CHANNEL_TASKS_SERVICE } from "@posthog/core/canvas/identifiers";
import type { IChannelTasksService } from "@posthog/core/canvas/services";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

export const channelTasksRouter = router({
  list: publicProcedure
    .input(listChannelTasksInput)
    .output(z.array(channelTaskRecordSchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<IChannelTasksService>(CHANNEL_TASKS_SERVICE)
        .list(input.channelId),
    ),
  file: publicProcedure
    .input(fileChannelTaskInput)
    .output(channelTaskRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IChannelTasksService>(CHANNEL_TASKS_SERVICE)
        .file(input),
    ),
  unfile: publicProcedure
    .input(unfileChannelTaskInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IChannelTasksService>(CHANNEL_TASKS_SERVICE)
        .unfile(input.taskId),
    ),
});
