import {
  authorizePreviewInput,
  authorizePreviewOutput,
} from "@posthog/core/task-browser/schemas";
import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  type ITaskPreviewSessions,
  TASK_PREVIEW_SESSIONS,
} from "@posthog/platform/task-browser";

const svc = (container: ServiceResolver) =>
  container.get<ITaskPreviewSessions>(TASK_PREVIEW_SESSIONS);

export const taskPreviewRouter = router({
  authorize: publicProcedure
    .input(authorizePreviewInput)
    .output(authorizePreviewOutput)
    .mutation(({ ctx, input }) => svc(ctx.container).authorize(input.url)),
});
