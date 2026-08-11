import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { logger } from "@posthog/ui/shell/logger";
import { inject, injectable } from "inversify";

const log = logger.scope("custom-instructions-sync");

/**
 * Mirrors the user-level AGENTS.md/CLAUDE.md into personalization while the
 * "sync from file" setting is on: reads the file once settings hydrate at
 * boot, and again whenever the toggle flips. The store only holds the snapshot
 * (AGENTS.md forbids stores owning I/O); this contribution owns the read.
 */
@injectable()
export class CustomInstructionsSyncContribution implements Contribution {
  /**
   * Bumped by every reconcile so an in-flight read that a newer toggle flip
   * has superseded cannot land its (now stale) snapshot in the store. The
   * read is a host round-trip, so on slower transports rapid toggling can
   * genuinely have two reads in flight resolving out of order.
   */
  private generation = 0;

  constructor(
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
  ) {}

  start(): void {
    const initial = useSettingsStore.getState();
    if (initial._hasHydrated) {
      void this.reconcile(initial.syncCustomInstructionsFromFile);
    }
    useSettingsStore.subscribe((state, prev) => {
      const wasUnhydrated = !prev._hasHydrated;
      const toggleFlipped =
        state.syncCustomInstructionsFromFile !==
        prev.syncCustomInstructionsFromFile;
      if (state._hasHydrated && (wasUnhydrated || toggleFlipped)) {
        void this.reconcile(state.syncCustomInstructionsFromFile);
      }
    });
  }

  private async reconcile(enabled: boolean): Promise<void> {
    const generation = ++this.generation;
    if (!enabled) {
      useSettingsStore.getState().setSyncedCustomInstructions(null);
      return;
    }
    // Drop any prior snapshot before the re-read resolves. Without this, a
    // session created while sync is being re-enabled (e.g. off then back on
    // after editing the file) would inject the stale snapshot from before the
    // toggle flip instead of nothing.
    useSettingsStore.getState().setSyncedCustomInstructions(null);
    try {
      const file = await this.hostClient.os.getUserAgentInstructions.query();
      // A newer toggle flip started its own reconcile while this read was in
      // flight; its outcome owns the store now.
      if (generation !== this.generation) return;
      useSettingsStore.getState().setSyncedCustomInstructions(file);
    } catch (err) {
      // The snapshot was already cleared above, so a transient read failure
      // here just leaves personalization empty rather than reviving stale
      // content.
      log.warn("Failed to read user agent instructions file", err);
    }
  }
}
