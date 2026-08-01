import type { AuthState } from "@posthog/core/auth/schemas";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { withTimeout } from "@posthog/shared";
import { toast } from "@posthog/ui/primitives/toast";
import { logger } from "@posthog/ui/shell/logger";
import { inject, injectable } from "inversify";
import { useAuthStore } from "./store";

const log = logger.scope("auth-contribution");
// boot() starts contributions serially, so a stuck host query must not wedge it.
const INITIAL_STATE_TIMEOUT_MS = 10_000;
const STRANDED_CLOUD_QUEUE_TOAST_ID = "stranded-cloud-queue";

@injectable()
export class AuthContribution implements Contribution {
  constructor(
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
    @inject(SESSION_SERVICE)
    private readonly sessionService: SessionService,
  ) {}

  async start(): Promise<void> {
    this.hostClient.auth.onStateChanged.subscribe(undefined, {
      onData: (state) => {
        useAuthStore.getState().setAuthState(state);
        this.syncCloudQueueForAuthState(state);
      },
    });

    const outcome = await withTimeout(
      this.hostClient.auth.getState.query(),
      INITIAL_STATE_TIMEOUT_MS,
    );
    if (outcome.result === "success") {
      useAuthStore.getState().setAuthState(outcome.value);
      this.syncCloudQueueForAuthState(outcome.value);
    } else {
      log.warn(
        "Initial auth state query timed out; relying on state subscription",
      );
    }
  }

  private syncCloudQueueForAuthState(state: AuthState): void {
    if (state.status === "authenticated") {
      this.sessionService.flushQueuedCloudMessagesAfterAuthRestored();
      return;
    }

    if (state.status === "anonymous") {
      const pending = this.sessionService.countQueuedCloudMessages();
      if (pending === 0) return;
      const noun = pending === 1 ? "message" : "messages";
      const pronoun = pending === 1 ? "it" : "them";
      toast.error(
        `You were signed out with ${pending} unsent cloud ${noun}. Sign in to send ${pronoun}.`,
        { id: STRANDED_CLOUD_QUEUE_TOAST_ID },
      );
    }
  }
}
