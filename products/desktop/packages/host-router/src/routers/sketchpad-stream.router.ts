import {
  type ISketchpadStreamService,
  SKETCHPAD_STREAM_SERVICE,
} from "@posthog/core/sketchpad/identifiers";
import {
  sketchpadIdInput,
  sketchpadSendPresenceInput,
} from "@posthog/core/sketchpad/sketchpadSchemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const sketchpadStreamRouter = router({
  onSketchpadEvent: publicProcedure
    .input(sketchpadIdInput)
    .subscription((opts) =>
      opts.ctx.container
        .get<ISketchpadStreamService>(SKETCHPAD_STREAM_SERVICE)
        .streamSketchpad(opts.input.id, opts.signal),
    ),
  sendPresence: publicProcedure
    .input(sketchpadSendPresenceInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadStreamService>(SKETCHPAD_STREAM_SERVICE)
        .sendPresence(input.id, input.presence),
    ),
});
