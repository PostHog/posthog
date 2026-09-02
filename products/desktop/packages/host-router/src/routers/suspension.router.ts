import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { SUSPENSION_SERVICE } from "@posthog/workspace-server/services/suspension/identifiers";
import {
  listSuspendedTasksOutput,
  restoreTaskInput,
  restoreTaskOutput,
  suspendedTaskIdsOutput,
  suspendTaskInput,
  suspendTaskOutput,
  suspensionSettingsOutput,
  updateSuspensionSettingsInput,
} from "@posthog/workspace-server/services/suspension/schemas";
import type { SuspensionService } from "@posthog/workspace-server/services/suspension/suspension";

export const suspensionRouter = router({
  suspend: publicProcedure
    .input(suspendTaskInput)
    .output(suspendTaskOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SuspensionService>(SUSPENSION_SERVICE)
        .suspendTask(input.taskId, input.reason),
    ),

  restore: publicProcedure
    .input(restoreTaskInput)
    .output(restoreTaskOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SuspensionService>(SUSPENSION_SERVICE)
        .restoreTask(input.taskId, input.recreateBranch),
    ),

  list: publicProcedure
    .output(listSuspendedTasksOutput)
    .query(({ ctx }) =>
      ctx.container
        .get<SuspensionService>(SUSPENSION_SERVICE)
        .getSuspendedTasks(),
    ),

  suspendedTaskIds: publicProcedure
    .output(suspendedTaskIdsOutput)
    .query(({ ctx }) =>
      ctx.container
        .get<SuspensionService>(SUSPENSION_SERVICE)
        .getSuspendedTaskIds(),
    ),

  settings: publicProcedure
    .output(suspensionSettingsOutput)
    .query(({ ctx }) =>
      ctx.container.get<SuspensionService>(SUSPENSION_SERVICE).getSettings(),
    ),

  updateSettings: publicProcedure
    .input(updateSuspensionSettingsInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SuspensionService>(SUSPENSION_SERVICE)
        .updateSettings(input),
    ),
});
