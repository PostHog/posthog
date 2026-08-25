import type { PlatformStatus } from "@posthog/core/platform-status/platformStatusStore";
import type { CloudRegion } from "@posthog/shared";

export interface PlatformStatusClient {
  getStatus(region: CloudRegion): Promise<PlatformStatus>;
}

export const PLATFORM_STATUS_CLIENT = Symbol.for(
  "posthog.ui.PlatformStatusClient",
);
