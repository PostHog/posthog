import { homeWorkInput } from "@posthog/core/home/homeSchemas";
import { HOME_SERVICE } from "@posthog/core/home/identifiers";
import type { IHomeService } from "@posthog/core/home/services";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

// The groups of work Home opens on. A one-line forward to HomeService, which
// injects the PostHog credentials host-side.
export const homeRouter = router({
  work: publicProcedure
    .input(homeWorkInput)
    .query(({ ctx, input }) =>
      ctx.container.get<IHomeService>(HOME_SERVICE).work(input),
    ),
});
