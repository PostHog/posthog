import {
  platformStatusInput,
  platformStatusOutput,
} from "@posthog/core/platform-status/schemas";
import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  type HostPlatformStatusClient,
  PLATFORM_STATUS_CLIENT,
} from "../ports/platform-status-client";

const platformStatus = (container: ServiceResolver) =>
  container.get<HostPlatformStatusClient>(PLATFORM_STATUS_CLIENT);

export const platformStatusRouter = router({
  getStatus: publicProcedure
    .input(platformStatusInput)
    .output(platformStatusOutput)
    .query(({ ctx, input }) =>
      platformStatus(ctx.container).getStatus(input.region),
    ),
});
