import { connectivityStore } from "@posthog/core/connectivity/connectivityStore";
import type { Contribution } from "@posthog/di/contribution";
import { inject, injectable } from "inversify";
import {
  CONNECTIVITY_CLIENT,
  type ConnectivityClient,
} from "./connectivityClient";
import { initializeConnectivityToast } from "./connectivityToast";

/**
 * Boots connectivity once at startup (formerly the platform-adapters/connectivity
 * side-effect module): seeds the domain online store from the host's current
 * status, keeps it in sync via the status-change subscription, and starts the
 * debounced offline toast.
 */
@injectable()
export class ConnectivityEventsContribution implements Contribution {
  constructor(
    @inject(CONNECTIVITY_CLIENT)
    private readonly client: ConnectivityClient,
  ) {}

  start(): void {
    const { setOnline } = connectivityStore.getState();

    void this.client
      .getStatus()
      .then((status) => setOnline(status.isOnline))
      .catch(() => undefined);

    this.client.onStatusChange({
      onData: (status) => setOnline(status.isOnline),
    });

    initializeConnectivityToast();
  }
}
