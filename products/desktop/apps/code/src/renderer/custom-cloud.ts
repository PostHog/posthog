import { configureCustomCloud } from "@posthog/shared";
import { trpcClient } from "@renderer/trpc/client";

// A renderer window resolves region URLs itself, so it needs the target that
// the main process holds before it renders a link or a region label.
export function hydrateCustomCloud(): void {
  void trpcClient.customCloud.get
    .query()
    .then(configureCustomCloud)
    .catch(() => undefined);
}
