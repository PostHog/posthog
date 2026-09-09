import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  SKETCHPAD_FRAME_HOST,
  type SketchpadFrameHost,
} from "@posthog/platform/sketchpad-frame";
import { z } from "zod";

export const sketchpadFrameRouter = router({
  registerDocument: publicProcedure
    .input(
      z.object({
        html: z.string().max(2_000_000),
        csp: z.string().max(4000),
      }),
    )
    .mutation(({ ctx, input }) => {
      ctx.container
        .get<SketchpadFrameHost>(SKETCHPAD_FRAME_HOST)
        .registerDocument(input);
      return { ok: true };
    }),
});
