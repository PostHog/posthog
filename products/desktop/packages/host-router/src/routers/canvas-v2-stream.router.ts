import {
  canvasV2BoardIdInput,
  canvasV2SendPresenceInput,
} from "@posthog/core/canvas-v2/canvasV2Schemas";
import {
  CANVAS_V2_STREAM_SERVICE,
  type ICanvasV2StreamService,
} from "@posthog/core/canvas-v2/identifiers";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const canvasV2StreamRouter = router({
  onBoardEvent: publicProcedure
    .input(canvasV2BoardIdInput)
    .subscription((opts) =>
      opts.ctx.container
        .get<ICanvasV2StreamService>(CANVAS_V2_STREAM_SERVICE)
        .streamBoard(opts.input.id, opts.signal),
    ),
  sendPresence: publicProcedure
    .input(canvasV2SendPresenceInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ICanvasV2StreamService>(CANVAS_V2_STREAM_SERVICE)
        .sendPresence(input.id, input.presence),
    ),
});
