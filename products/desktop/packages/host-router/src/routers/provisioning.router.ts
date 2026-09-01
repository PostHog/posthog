import { PROVISIONING_SERVICE } from "@posthog/core/provisioning/identifiers";
import {
  ProvisioningEvent,
  type ProvisioningService,
} from "@posthog/core/provisioning/provisioning";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const provisioningRouter = router({
  onOutput: publicProcedure.subscription(async function* (opts) {
    const service =
      opts.ctx.container.get<ProvisioningService>(PROVISIONING_SERVICE);
    for await (const data of service.toIterable(ProvisioningEvent.Output, {
      signal: opts.signal,
    })) {
      yield data;
    }
  }),
});
