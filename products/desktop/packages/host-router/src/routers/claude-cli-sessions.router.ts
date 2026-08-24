import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  CLAUDE_CLI_SESSIONS_SERVICE,
  type ClaudeCliSessionsService,
} from "@posthog/workspace-server/services/claude-cli-sessions/identifiers";
import {
  deleteImportedCliSessionInput,
  deleteImportRecordInput,
  importCliSessionInput,
  importCliSessionOutput,
  listCliSessionsInput,
  listCliSessionsOutput,
  recordCliImportInput,
} from "@posthog/workspace-server/services/claude-cli-sessions/schemas";

export const claudeCliSessionsRouter = router({
  list: publicProcedure
    .input(listCliSessionsInput)
    .output(listCliSessionsOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ClaudeCliSessionsService>(CLAUDE_CLI_SESSIONS_SERVICE)
        .listForRepo(input),
    ),

  import: publicProcedure
    .input(importCliSessionInput)
    .output(importCliSessionOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ClaudeCliSessionsService>(CLAUDE_CLI_SESSIONS_SERVICE)
        .importSession(input),
    ),

  deleteImport: publicProcedure
    .input(deleteImportedCliSessionInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ClaudeCliSessionsService>(CLAUDE_CLI_SESSIONS_SERVICE)
        .deleteImportedSession(input),
    ),

  recordImport: publicProcedure
    .input(recordCliImportInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ClaudeCliSessionsService>(CLAUDE_CLI_SESSIONS_SERVICE)
        .recordImport(input),
    ),

  deleteImportRecord: publicProcedure
    .input(deleteImportRecordInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ClaudeCliSessionsService>(CLAUDE_CLI_SESSIONS_SERVICE)
        .deleteImportRecord(input),
    ),
});
