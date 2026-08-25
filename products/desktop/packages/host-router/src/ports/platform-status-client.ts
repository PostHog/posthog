import type { PlatformStatus } from "@posthog/core/platform-status/platformStatusStore";
import type { CloudRegion } from "@posthog/shared";

export const PLATFORM_STATUS_CLIENT = Symbol.for(
  "posthog.host.platformStatusClient",
);

export interface HostPlatformStatusClient {
  getStatus(region: CloudRegion): Promise<PlatformStatus>;
}
