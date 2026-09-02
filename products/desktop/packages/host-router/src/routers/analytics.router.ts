import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import type { IAnalytics } from "@posthog/platform/analytics";
import { ANALYTICS_SERVICE } from "@posthog/platform/analytics";
import { z } from "zod";

export const analyticsRouter = router({
  setUserId: publicProcedure
    .input(
      z.object({
        userId: z.string(),
        properties: z
          .record(z.string(), z.union([z.string(), z.number(), z.boolean()]))
          .optional(),
      }),
    )
    .mutation(({ ctx, input }) => {
      const analytics = ctx.container.get<IAnalytics>(ANALYTICS_SERVICE);
      analytics.setCurrentUserId(input.userId);
      if (input.properties) {
        analytics.identify(
          input.userId,
          input.properties as Record<string, string | number | boolean>,
        );
      }
    }),

  getSessionId: publicProcedure
    .output(z.object({ sessionId: z.string() }))
    .query(({ ctx }) => ({
      sessionId: ctx.container
        .get<IAnalytics>(ANALYTICS_SERVICE)
        .getOrCreateSessionId(),
    })),

  resetUser: publicProcedure.mutation(({ ctx }) => {
    ctx.container.get<IAnalytics>(ANALYTICS_SERVICE).resetUser();
  }),
});
