import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { PROCESS_TRACKING_SERVICE } from "@posthog/workspace-server/services/process-tracking/identifiers";
import type { ProcessTrackingService } from "@posthog/workspace-server/services/process-tracking/process-tracking";
import {
  getSnapshotInput,
  killByCategoryInput,
  killByPidInput,
  killByTaskIdInput,
  listByTaskIdInput,
} from "@posthog/workspace-server/services/process-tracking/schemas";

export const processTrackingRouter = router({
  getSnapshot: publicProcedure
    .input(getSnapshotInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ProcessTrackingService>(PROCESS_TRACKING_SERVICE)
        .getSnapshot(input?.includeDiscovered ?? false),
    ),

  list: publicProcedure.query(({ ctx }) =>
    ctx.container
      .get<ProcessTrackingService>(PROCESS_TRACKING_SERVICE)
      .getAll(),
  ),

  kill: publicProcedure.input(killByPidInput).mutation(({ ctx, input }) => {
    ctx.container
      .get<ProcessTrackingService>(PROCESS_TRACKING_SERVICE)
      .kill(input.pid);
  }),

  killByCategory: publicProcedure
    .input(killByCategoryInput)
    .mutation(({ ctx, input }) => {
      ctx.container
        .get<ProcessTrackingService>(PROCESS_TRACKING_SERVICE)
        .killByCategory(input.category);
    }),

  killByTaskId: publicProcedure
    .input(killByTaskIdInput)
    .mutation(({ ctx, input }) => {
      ctx.container
        .get<ProcessTrackingService>(PROCESS_TRACKING_SERVICE)
        .killByTaskId(input.taskId);
    }),

  listByTaskId: publicProcedure
    .input(listByTaskIdInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ProcessTrackingService>(PROCESS_TRACKING_SERVICE)
        .getByTaskId(input.taskId),
    ),

  killAll: publicProcedure.mutation(({ ctx }) => {
    ctx.container
      .get<ProcessTrackingService>(PROCESS_TRACKING_SERVICE)
      .killAll();
  }),
});
