import {
  PLATFORM_STATUS_CLIENT,
  type PlatformStatusClient,
} from "@posthog/core/platform-status/identifiers";
import {
  platformStatusInput,
  platformStatusOutput,
} from "@posthog/core/platform-status/schemas";
import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

const platformStatus = (container: ServiceResolver) =>
  container.get<PlatformStatusClient>(PLATFORM_STATUS_CLIENT);

export const platformStatusRouter = router({
  getStatus: publicProcedure
    .input(platformStatusInput)
    .output(platformStatusOutput)
    .query(({ ctx, input }) =>
      platformStatus(ctx.container).getStatus(input.region),
    ),
});
