import { configureCustomCloud } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { trpcClient } from "@renderer/trpc/client";

const log = logger.scope("custom-cloud");

// A renderer window resolves region URLs itself, so it needs the target that
// the main process holds before it renders a link or a region label. Boot
// awaits this, because a memoized read of an unhydrated target would keep the
// empty value for the whole session.
export function hydrateCustomCloud(): Promise<void> {
  return trpcClient.customCloud.get
    .query()
    .then((target) => {
      configureCustomCloud(target);
    })
    .catch((error: unknown) => {
      // Boot continues without a target; only custom sessions need one.
      log.error("Could not read the custom cloud target", error);
    });
}
