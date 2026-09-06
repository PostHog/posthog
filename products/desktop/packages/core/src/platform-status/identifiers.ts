import type { CloudRegion } from "@posthog/shared";
import type { PlatformStatus } from "./platformStatusStore";

export const PLATFORM_STATUS_CLIENT = Symbol.for(
  "posthog.core.platformStatusClient",
);

export interface PlatformStatusClient {
  getStatus(region: CloudRegion): Promise<PlatformStatus>;
}

export const PLATFORM_STATUS_SERVICE = Symbol.for(
  "posthog.core.platformStatusService",
);
