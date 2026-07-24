import { CANVAS_TEMPLATES_SERVICE } from "@posthog/core/canvas/identifiers";
import type { ICanvasTemplatesService } from "@posthog/core/canvas/services";
import {
  canvasTemplateSchema,
  canvasTemplateSummarySchema,
  getCanvasTemplateInput,
} from "@posthog/core/canvas/templateSchemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

export const canvasTemplatesRouter = router({
  list: publicProcedure
    .output(z.array(canvasTemplateSummarySchema))
    .query(({ ctx }) =>
      ctx.container
        .get<ICanvasTemplatesService>(CANVAS_TEMPLATES_SERVICE)
        .list(),
    ),
  get: publicProcedure
    .input(getCanvasTemplateInput)
    .output(canvasTemplateSchema.nullable())
    .query(
      ({ ctx, input }) =>
        ctx.container
          .get<ICanvasTemplatesService>(CANVAS_TEMPLATES_SERVICE)
          .get(input.id) ?? null,
    ),
});
