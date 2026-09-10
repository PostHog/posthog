import type { ConnectivityStatusOutput } from "@posthog/workspace-server/services/connectivity/schemas";

export const CONNECTIVITY_CLIENT = Symbol.for(
  "posthog.host.connectivityClient",
);

export interface HostConnectivityClient {
  getStatus(): ConnectivityStatusOutput;
  checkNow(): Promise<ConnectivityStatusOutput>;
  onStatusChange(
    handler: (status: ConnectivityStatusOutput) => void,
  ): () => void;
}
