import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  FEEDBACK_CONTEXT_SERVICE,
  type IFeedbackContext,
} from "@posthog/platform/feedback-context";
import {
  feedbackLogsOutput,
  feedbackScreenshotOutput,
} from "./feedback-context.schemas";

export const feedbackContextRouter = router({
  captureScreenshot: publicProcedure
    .output(feedbackScreenshotOutput)
    .query(({ ctx }) =>
      ctx.container
        .get<IFeedbackContext>(FEEDBACK_CONTEXT_SERVICE)
        .captureScreenshot(),
    ),
  readRecentLogs: publicProcedure
    .output(feedbackLogsOutput)
    .query(({ ctx }) =>
      ctx.container
        .get<IFeedbackContext>(FEEDBACK_CONTEXT_SERVICE)
        .readRecentLogs(),
    ),
});
