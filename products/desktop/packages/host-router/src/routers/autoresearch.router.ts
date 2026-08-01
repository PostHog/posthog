import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { AUTORESEARCH_RUN_REPOSITORY } from "@posthog/workspace-server/db/identifiers";
import type { IAutoresearchRunRepository } from "@posthog/workspace-server/db/repositories/autoresearch-run-repository";
import { z } from "zod";

const storedRunSchema = z.object({
  id: z.string().min(1),
  taskId: z.string().min(1),
  endedAt: z.string().nullable(),
  data: z.string().min(1),
});

export const autoresearchRouter = router({
  save: publicProcedure
    .input(storedRunSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IAutoresearchRunRepository>(AUTORESEARCH_RUN_REPOSITORY)
        .upsert(input),
    ),

  listOpen: publicProcedure
    .output(z.array(storedRunSchema))
    .query(({ ctx }) =>
      ctx.container
        .get<IAutoresearchRunRepository>(AUTORESEARCH_RUN_REPOSITORY)
        .findOpen(),
    ),

  listByTask: publicProcedure
    .input(z.object({ taskId: z.string().min(1) }))
    .output(z.array(storedRunSchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<IAutoresearchRunRepository>(AUTORESEARCH_RUN_REPOSITORY)
        .findByTaskId(input.taskId),
    ),
});
