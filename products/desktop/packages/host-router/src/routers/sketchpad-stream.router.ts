import {
  type ISketchpadStreamService,
  SKETCHPAD_STREAM_SERVICE,
} from "@posthog/core/sketchpad/identifiers";
import {
  sketchpadIdInput,
  sketchpadSendPresenceInput,
} from "@posthog/core/sketchpad/sketchpadSchemas";
import { httpStatusProcedure, router } from "@posthog/host-trpc/trpc";

export const sketchpadStreamRouter = router({
  onSketchpadEvent: httpStatusProcedure
    .input(sketchpadIdInput)
    .subscription((opts) =>
      opts.ctx.container
        .get<ISketchpadStreamService>(SKETCHPAD_STREAM_SERVICE)
        .streamSketchpad(opts.input.id, opts.signal),
    ),
  sendPresence: httpStatusProcedure
    .input(sketchpadSendPresenceInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISketchpadStreamService>(SKETCHPAD_STREAM_SERVICE)
        .sendPresence(input.id, input.presence),
    ),
});
