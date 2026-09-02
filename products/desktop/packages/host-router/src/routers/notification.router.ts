import { NOTIFICATION_SERVICE } from "@posthog/core/notification/identifiers";
import type { NotificationService } from "@posthog/core/notification/notification";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

// Mirrors the `NotificationTarget` union in @posthog/platform/notifications.
// Kept in lockstep by a type-parity test (notification-target.test.ts).
export const notificationTargetSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("task"),
    taskId: z.string(),
    taskRunId: z.string().optional(),
  }),
  z.object({
    kind: z.literal("canvas"),
    channelId: z.string(),
    dashboardId: z.string(),
  }),
]);

export const notificationRouter = router({
  send: publicProcedure
    .input(
      z.object({
        title: z.string(),
        body: z.string(),
        silent: z.boolean(),
        target: notificationTargetSchema.optional(),
      }),
    )
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<NotificationService>(NOTIFICATION_SERVICE)
        .send(input.title, input.body, input.silent, input.target),
    ),
  showDockBadge: publicProcedure.mutation(({ ctx }) =>
    ctx.container
      .get<NotificationService>(NOTIFICATION_SERVICE)
      .showDockBadge(),
  ),
  bounceDock: publicProcedure.mutation(({ ctx }) =>
    ctx.container.get<NotificationService>(NOTIFICATION_SERVICE).bounceDock(),
  ),
});
