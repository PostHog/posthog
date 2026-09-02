import { SLEEP_SERVICE } from "@posthog/core/sleep/identifiers";
import type { SleepService } from "@posthog/core/sleep/sleep";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

export const sleepRouter = router({
  getEnabled: publicProcedure
    .output(z.boolean())
    .query(({ ctx }) =>
      ctx.container.get<SleepService>(SLEEP_SERVICE).getEnabled(),
    ),

  setEnabled: publicProcedure
    .input(z.object({ enabled: z.boolean() }))
    .mutation(({ ctx, input }) => {
      ctx.container.get<SleepService>(SLEEP_SERVICE).setEnabled(input.enabled);
    }),

  hasBuiltInBattery: publicProcedure
    .output(z.boolean())
    .query(({ ctx }) =>
      ctx.container.get<SleepService>(SLEEP_SERVICE).hasBuiltInBattery(),
    ),
});
