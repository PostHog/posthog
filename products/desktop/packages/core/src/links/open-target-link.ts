import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import type { NotificationTarget } from "@posthog/platform/notifications";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { LinkLogger } from "./identifiers";

export const OpenTargetLinkEvent = {
  Open: "open",
} as const;

export interface OpenTargetLinkEvents {
  [OpenTargetLinkEvent.Open]: NotificationTarget;
}

// Carries "open this target" intents (from a clicked native notification) out of
// the main process to the renderer, which navigates by target kind. Mirrors
// TaskLinkService's pending-replay + window-focus, but registers NO OS
// URL-scheme handler — notification clicks are its only source, so it stays
// target-generic without entangling URL parsing.
@injectable()
export class OpenTargetLinkService extends TypedEventEmitter<OpenTargetLinkEvents> {
  private pending: NotificationTarget | null = null;
  private readonly log: LinkLogger;

  constructor(
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: IMainWindow,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    super();
    this.log = rootLogger.scope("open-target-link-service");
  }

  // Called from the notification click handler (main process). Emits to the
  // renderer if it's listening, else queues for replay once it subscribes.
  open(target: NotificationTarget): void {
    if (this.listenerCount(OpenTargetLinkEvent.Open) > 0) {
      this.log.info("Emitting open-target event", { kind: target.kind });
      this.emit(OpenTargetLinkEvent.Open, target);
    } else {
      this.log.info("Queueing open-target (renderer not ready)", {
        kind: target.kind,
      });
      this.pending = target;
    }

    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();
  }

  consumePending(): NotificationTarget | null {
    const pending = this.pending;
    this.pending = null;
    return pending;
  }
}
