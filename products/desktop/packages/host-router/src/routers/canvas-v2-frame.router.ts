import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  CANVAS_BOARD_FRAME_HOST,
  type CanvasBoardFrameHost,
} from "@posthog/platform/canvas-board-frame";
import { z } from "zod";

export const canvasV2FrameRouter = router({
  registerDocument: publicProcedure
    .input(
      z.object({
        html: z.string().max(2_000_000),
        csp: z.string().max(4000),
      }),
    )
    .mutation(({ ctx, input }) => {
      ctx.container
        .get<CanvasBoardFrameHost>(CANVAS_BOARD_FRAME_HOST)
        .registerDocument(input);
      return { ok: true };
    }),
});
