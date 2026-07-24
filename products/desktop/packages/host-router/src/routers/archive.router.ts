import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import type { ArchiveService } from "@posthog/workspace-server/services/archive/archive";
import { ARCHIVE_SERVICE } from "@posthog/workspace-server/services/archive/identifiers";
import {
  archivedTaskIdsOutput,
  archiveTaskInput,
  archiveTaskOutput,
  deleteArchivedTaskInput,
  deleteArchivedTaskOutput,
  listArchivedTasksOutput,
  unarchiveTaskInput,
  unarchiveTaskOutput,
} from "@posthog/workspace-server/services/archive/schemas";

export const archiveRouter = router({
  archive: publicProcedure
    .input(archiveTaskInput)
    .output(archiveTaskOutput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<ArchiveService>(ARCHIVE_SERVICE).archiveTask(input),
    ),

  unarchive: publicProcedure
    .input(unarchiveTaskInput)
    .output(unarchiveTaskOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ArchiveService>(ARCHIVE_SERVICE)
        .unarchiveTask(input.taskId, input.recreateBranch),
    ),

  list: publicProcedure
    .output(listArchivedTasksOutput)
    .query(({ ctx }) =>
      ctx.container.get<ArchiveService>(ARCHIVE_SERVICE).listArchivedTasks(),
    ),

  archivedTaskIds: publicProcedure
    .output(archivedTaskIdsOutput)
    .query(({ ctx }) =>
      ctx.container.get<ArchiveService>(ARCHIVE_SERVICE).getArchivedTaskIds(),
    ),

  delete: publicProcedure
    .input(deleteArchivedTaskInput)
    .output(deleteArchivedTaskOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ArchiveService>(ARCHIVE_SERVICE)
        .deleteArchivedTask(input.taskId),
    ),
});
