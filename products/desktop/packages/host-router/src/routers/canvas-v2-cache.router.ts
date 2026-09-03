import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  CANVAS_V2_CACHE_SERVICE,
  type CanvasV2CacheService,
} from "@posthog/workspace-server/services/canvas-v2-cache/identifiers";
import { writeCanvasV2CacheInput } from "@posthog/workspace-server/services/canvas-v2-cache/schemas";

export const canvasV2CacheRouter = router({
  write: publicProcedure
    .input(writeCanvasV2CacheInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<CanvasV2CacheService>(CANVAS_V2_CACHE_SERVICE)
        .write(input.boardId, input.payload),
    ),
});
