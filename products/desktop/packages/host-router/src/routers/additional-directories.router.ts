import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import type { AdditionalDirectoriesService } from "@posthog/workspace-server/services/additional-directories/additional-directories";
import { ADDITIONAL_DIRECTORIES_SERVICE } from "@posthog/workspace-server/services/additional-directories/identifiers";
import { z } from "zod";

const pathInput = z.object({ path: z.string().min(1) });
const taskPathInput = z.object({
  taskId: z.string(),
  path: z.string().min(1),
});
const ok = { ok: true as const };

export const additionalDirectoriesRouter = router({
  listDefaults: publicProcedure
    .output(z.array(z.string()))
    .query(({ ctx }) =>
      ctx.container
        .get<AdditionalDirectoriesService>(ADDITIONAL_DIRECTORIES_SERVICE)
        .listDefaults(),
    ),

  listForTask: publicProcedure
    .input(z.object({ taskId: z.string() }))
    .output(z.array(z.string()))
    .query(({ ctx, input }) =>
      ctx.container
        .get<AdditionalDirectoriesService>(ADDITIONAL_DIRECTORIES_SERVICE)
        .listForTask(input.taskId),
    ),

  addDefault: publicProcedure.input(pathInput).mutation(({ ctx, input }) => {
    ctx.container
      .get<AdditionalDirectoriesService>(ADDITIONAL_DIRECTORIES_SERVICE)
      .addDefault(input.path);
    return ok;
  }),

  removeDefault: publicProcedure.input(pathInput).mutation(({ ctx, input }) => {
    ctx.container
      .get<AdditionalDirectoriesService>(ADDITIONAL_DIRECTORIES_SERVICE)
      .removeDefault(input.path);
    return ok;
  }),

  addForTask: publicProcedure
    .input(taskPathInput)
    .mutation(({ ctx, input }) => {
      ctx.container
        .get<AdditionalDirectoriesService>(ADDITIONAL_DIRECTORIES_SERVICE)
        .addForTask(input.taskId, input.path);
      return ok;
    }),

  removeForTask: publicProcedure
    .input(taskPathInput)
    .mutation(({ ctx, input }) => {
      ctx.container
        .get<AdditionalDirectoriesService>(ADDITIONAL_DIRECTORIES_SERVICE)
        .removeForTask(input.taskId, input.path);
      return ok;
    }),
});
