import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import type { ILogsService } from "@posthog/workspace-server/services/local-logs/identifiers";
import { LOGS_SERVICE } from "@posthog/workspace-server/services/local-logs/identifiers";
import {
  fetchS3LogsInput,
  fetchS3LogsOutput,
  readLocalLogsCollapsedInput,
  readLocalLogsCollapsedOutput,
  readLocalLogsInput,
  readLocalLogsOutput,
  readLocalLogsTailInput,
  readLocalLogsTailOutput,
  writeLocalLogsInput,
} from "@posthog/workspace-server/services/local-logs/schemas";

export const logsRouter = router({
  fetchS3Logs: publicProcedure
    .input(fetchS3LogsInput)
    .output(fetchS3LogsOutput)
    .query(({ ctx, input }) =>
      ctx.container.get<ILogsService>(LOGS_SERVICE).fetchS3Logs(input.logUrl),
    ),

  readLocalLogs: publicProcedure
    .input(readLocalLogsInput)
    .output(readLocalLogsOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ILogsService>(LOGS_SERVICE)
        .readLocalLogs(input.taskRunId),
    ),

  readLocalLogsCollapsed: publicProcedure
    .input(readLocalLogsCollapsedInput)
    .output(readLocalLogsCollapsedOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ILogsService>(LOGS_SERVICE)
        .readLocalLogsCollapsed(input.taskRunId),
    ),

  readLocalLogsTail: publicProcedure
    .input(readLocalLogsTailInput)
    .output(readLocalLogsTailOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ILogsService>(LOGS_SERVICE)
        .readLocalLogsTail(input.taskRunId, input.maxBytes),
    ),

  writeLocalLogs: publicProcedure
    .input(writeLocalLogsInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ILogsService>(LOGS_SERVICE)
        .writeLocalLogs(input.taskRunId, input.content),
    ),
});
