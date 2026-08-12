import { connectivityStore } from "@posthog/core/connectivity/connectivityStore";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import type { Contribution } from "@posthog/di/contribution";
import { inject, injectable } from "inversify";

/**
 * On an offline→online transition, asks the session service to recover cloud
 * sessions. Window-focus and auth-restored already trigger the same recovery;
 * this covers the reconnect event, which fired neither. Local sessions recover
 * on their own via `reconcileLocalConnection`.
 */
@injectable()
export class NetworkReconnectContribution implements Contribution {
  constructor(
    @inject(SESSION_SERVICE)
    private readonly sessionService: SessionService,
  ) {}

  start(): void {
    let wasOnline = connectivityStore.getState().isOnline;
    connectivityStore.subscribe((state) => {
      const justCameOnline = !wasOnline && state.isOnline;
      wasOnline = state.isOnline;
      if (justCameOnline) {
        this.sessionService.recoverAfterReconnect();
      }
    });
  }
}
