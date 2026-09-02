import type { WorkspaceClient } from "@posthog/workspace-client/client";

export const ENVIRONMENT_CLIENT = Symbol.for("posthog.host.environmentClient");

export interface HostEnvironmentClient {
  environment: WorkspaceClient["environment"];
}
