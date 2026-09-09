import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { sketchpadCacheSchema } from "@posthog/shared";
import {
  SKETCHPAD_CACHE_SERVICE,
  type SketchpadCacheService,
} from "@posthog/workspace-server/services/sketchpad-cache/identifiers";

export const sketchpadCacheRouter = router({
  write: publicProcedure
    .input(sketchpadCacheSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SketchpadCacheService>(SKETCHPAD_CACHE_SERVICE)
        .write(input),
    ),
});
