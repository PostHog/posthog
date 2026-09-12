import { platformStatusStore } from "@posthog/core/platform-status/platformStatusStore";
import { createSelectors } from "@posthog/ui/hooks/createSelectors";

const platformStatus = createSelectors(platformStatusStore);

export function usePlatformStatus() {
  return platformStatus.use.status();
}
