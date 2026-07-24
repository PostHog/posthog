import type { Contribution } from "@posthog/di/contribution";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { sleepWithBackoff } from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "./browserTabsClient";
import { applyRemoteSnapshot, registerSnapshotFetcher } from "./tabsSync";

const SEED_ATTEMPTS = 3;
const SEED_RETRY_BASE_MS = 1_000;

/**
 * Seeds the renderer tab snapshot at startup and keeps it live via the
 * snapshot-change subscription, so a mutation in any window is reflected here.
 * Applied through the tabsSync gate: pushes are dropped while this window has
 * writes in flight, so an echo of our own mutation can't rewind newer local
 * state (see tabsSync.ts).
 */
@injectable()
export class BrowserTabsEventsContribution implements Contribution {
  private subscription: { unsubscribe: () => void } | null = null;
  private seedAbort: AbortController | null = null;
  private readonly logger;

  constructor(
    @inject(BROWSER_TABS_CLIENT)
    private readonly client: BrowserTabsClient,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    this.logger = logger.scope("browser-tabs-events");
  }

  start(): void {
    // Lets tabsSync re-pull the authoritative snapshot after a FAILED write
    // (a failed mutation emits no snapshotChange, so nothing else reconciles).
    registerSnapshotFetcher(() => this.client.getSnapshot());

    // Abort any prior loop so a repeated start() can't stack a second one
    // (mirrors the subscription replacement below).
    this.seedAbort?.abort();
    this.seedAbort = new AbortController();
    void this.seedWithRetry(this.seedAbort.signal);

    // Replace any prior handle so a repeated start() can't leak a subscription.
    this.subscription?.unsubscribe();
    this.subscription = this.client.onSnapshotChange({
      onData: (snapshot) => applyRemoteSnapshot(snapshot),
    });
  }

  // A failed seed used to be swallowed, leaving the mirror windowless forever —
  // the strip renders only a dead "+" in that state. Retry with backoff, and
  // make the terminal failure loud so a broken service can't fail silently.
  // Abort-aware: stop() must cancel the backoff and prevent a late snapshot
  // from applying after teardown.
  private async seedWithRetry(signal: AbortSignal): Promise<void> {
    for (let attempt = 1; attempt <= SEED_ATTEMPTS; attempt++) {
      if (signal.aborted) return;
      try {
        const snapshot = await this.client.getSnapshot();
        if (signal.aborted) return;
        applyRemoteSnapshot(snapshot);
        return;
      } catch (error) {
        if (signal.aborted) return;
        if (attempt === SEED_ATTEMPTS) {
          this.logger.error("browser-tabs snapshot seed failed", { error });
          return;
        }
        await sleepWithBackoff(
          attempt - 1,
          { initialDelayMs: SEED_RETRY_BASE_MS },
          signal,
        );
      }
    }
  }

  stop(): void {
    this.seedAbort?.abort();
    this.seedAbort = null;
    registerSnapshotFetcher(null);
    this.subscription?.unsubscribe();
    this.subscription = null;
  }
}
