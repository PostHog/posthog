import { removalDelayMsForStatus } from "@posthog/core/clone/cloneRemovalDelay";
import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { cloneStore } from "@posthog/ui/features/clone/cloneStore";
import { inject, injectable } from "inversify";

/**
 * Owns the single clone-progress subscription and the auto-dismiss lifecycle.
 *
 * The store stays a pure projection of progress events; the timer that hides a
 * finished clone card lives here, in the boot contribution, not in the store
 * (AGENTS.md forbids stores owning subscriptions or domain-cleanup timers).
 */
@injectable()
export class CloneContribution implements Contribution {
  private readonly pendingRemovals = new Map<
    string,
    ReturnType<typeof setTimeout>
  >();

  constructor(
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
  ) {}

  start(): void {
    this.hostClient.git.onCloneProgress.subscribe(undefined, {
      onData: (event) => {
        cloneStore.getState().applyProgress(event);

        const delayMs = removalDelayMsForStatus(event.status);
        if (delayMs !== null) {
          this.scheduleRemoval(event.cloneId, delayMs);
        }
      },
    });
  }

  private scheduleRemoval(cloneId: string, delayMs: number): void {
    const existing = this.pendingRemovals.get(cloneId);
    if (existing) clearTimeout(existing);

    this.pendingRemovals.set(
      cloneId,
      setTimeout(() => {
        this.pendingRemovals.delete(cloneId);
        cloneStore.getState().removeClone(cloneId);
      }, delayMs),
    );
  }
}
