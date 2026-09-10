import {
  type ISketchpadService,
  SKETCHPAD_BOARDS_SERVICE,
} from "@posthog/core/sketchpad/identifiers";
import {
  createSketchpadInput,
  sketchpadIdInput,
  sketchpadListInput,
  sketchpadOpsSinceInput,
  updateSketchpadInput,
} from "@posthog/core/sketchpad/sketchpadSchemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  sketchpadAppendOpsInputSchema,
  sketchpadAppendOpsResultSchema,
  sketchpadCompiledResultsSchema,
  sketchpadCompileRefsSchema,
  sketchpadOpsPageSchema,
  sketchpadSchema,
  sketchpadSummarySchema,
} from "@posthog/shared";
import { z } from "zod";

export const sketchpadRouter = router({
  compiled: publicProcedure
    .input(sketchpadIdInput.extend({ refs: sketchpadCompileRefsSchema }))
    .output(sketchpadCompiledResultsSchema)
    .query(({ ctx, input, signal }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .compiled(input.id, input.refs, signal),
    ),
  list: publicProcedure
    .input(sketchpadListInput)
    .output(z.array(sketchpadSummarySchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .list(input.channelId),
    ),
  get: publicProcedure
    .input(sketchpadIdInput)
    .output(sketchpadSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .get(input.id),
    ),
  create: publicProcedure
    .input(createSketchpadInput)
    .output(sketchpadSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .create(input.channelId, input.name),
    ),
  update: publicProcedure
    .input(updateSketchpadInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .update(input.id, input.patch),
    ),
  remove: publicProcedure
    .input(sketchpadIdInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .remove(input.id),
    ),
  opsSince: publicProcedure
    .input(sketchpadOpsSinceInput)
    .output(sketchpadOpsPageSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .opsSince(input.id, input.since, input.limit),
    ),
  appendOps: publicProcedure
    .input(sketchpadAppendOpsInputSchema.extend(sketchpadIdInput.shape))
    .output(sketchpadAppendOpsResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .appendOps(input.id, {
          ops: input.ops,
          actor: input.actor,
        }),
    ),
});
