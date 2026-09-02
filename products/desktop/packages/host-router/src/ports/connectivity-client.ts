import type { WorkspaceClient } from "@posthog/workspace-client/client";

export const CONNECTIVITY_CLIENT = Symbol.for(
  "posthog.host.connectivityClient",
);

export interface HostConnectivityClient {
  connectivity: WorkspaceClient["connectivity"];
}
