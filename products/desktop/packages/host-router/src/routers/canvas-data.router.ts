import {
  canvasCaptureConfigSchema,
  canvasCaptureInput,
  canvasDataQueryInput,
  canvasLoadInsightInput,
  savedInsightSchema,
} from "@posthog/core/canvas/freeformSchemas";
import { CANVAS_DATA_SERVICE } from "@posthog/core/canvas/identifiers";
import type { ICanvasDataService } from "@posthog/core/canvas/services";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

// The data avenue behind a freeform canvas's `ph.*` shims. One-line forwards to
// CanvasDataService, which injects the PostHog credentials host-side.
export const canvasDataRouter = router({
  query: publicProcedure
    .input(canvasDataQueryInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<ICanvasDataService>(CANVAS_DATA_SERVICE).query(input),
    ),
  loadInsight: publicProcedure
    .input(canvasLoadInsightInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ICanvasDataService>(CANVAS_DATA_SERVICE)
        .loadInsight(input),
    ),
  savedInsights: publicProcedure
    .input(z.object({ search: z.string().max(200).optional() }).optional())
    .output(z.array(savedInsightSchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<ICanvasDataService>(CANVAS_DATA_SERVICE)
        .listSavedInsights(input?.search),
    ),
  capture: publicProcedure
    .input(canvasCaptureInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<ICanvasDataService>(CANVAS_DATA_SERVICE).capture(input),
    ),
  captureConfig: publicProcedure
    .output(canvasCaptureConfigSchema)
    .query(({ ctx }) =>
      ctx.container
        .get<ICanvasDataService>(CANVAS_DATA_SERVICE)
        .captureConfig(),
    ),
});
