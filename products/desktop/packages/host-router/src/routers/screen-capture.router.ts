import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  type IScreenCapture,
  SCREEN_CAPTURE_SERVICE,
} from "@posthog/platform/screen-capture";
import { z } from "zod";

const regionInput = z.object({
  x: z.number().finite().min(0),
  y: z.number().finite().min(0),
  width: z.number().finite().positive().max(10_000),
  height: z.number().finite().positive().max(10_000),
});

export const screenCaptureRouter = router({
  captureRegion: publicProcedure
    .input(regionInput)
    .output(z.string().max(12_000_000).nullable())
    .query(({ ctx, input }) =>
      ctx.container
        .get<IScreenCapture>(SCREEN_CAPTURE_SERVICE)
        .captureRegion(input),
    ),
});
