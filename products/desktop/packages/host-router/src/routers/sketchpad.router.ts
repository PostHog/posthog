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
import { httpStatusProcedure, router } from "@posthog/host-trpc/trpc";
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
  compiled: httpStatusProcedure
    .input(sketchpadIdInput.extend({ refs: sketchpadCompileRefsSchema }))
    .output(sketchpadCompiledResultsSchema)
    .query(({ ctx, input, signal }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .compiled(input.id, input.refs, signal),
    ),
  list: httpStatusProcedure
    .input(sketchpadListInput)
    .output(z.array(sketchpadSummarySchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .list(input.channelId),
    ),
  get: httpStatusProcedure
    .input(sketchpadIdInput)
    .output(sketchpadSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .get(input.id),
    ),
  create: httpStatusProcedure
    .input(createSketchpadInput)
    .output(sketchpadSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .create(input.channelId, input.name),
    ),
  update: httpStatusProcedure
    .input(updateSketchpadInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .update(input.id, input.patch),
    ),
  remove: httpStatusProcedure
    .input(sketchpadIdInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .remove(input.id),
    ),
  opsSince: httpStatusProcedure
    .input(sketchpadOpsSinceInput)
    .output(sketchpadOpsPageSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadService>(SKETCHPAD_BOARDS_SERVICE)
        .opsSince(input.id, input.since, input.limit),
    ),
  appendOps: httpStatusProcedure
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
