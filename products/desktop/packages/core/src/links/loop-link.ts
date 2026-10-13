import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  DEEP_LINK_SERVICE,
  type IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { LinkLogger } from "./identifiers";

export const LoopLinkEvent = {
  OpenLoop: "openLoop",
} as const;

export interface LoopLinkPayload {
  /** Loop id, matching the `/loops/$loopId` route param. */
  loopId: string;
}

export interface LoopLinkEvents {
  [LoopLinkEvent.OpenLoop]: LoopLinkPayload;
}

@injectable()
export class LoopLinkService extends TypedEventEmitter<LoopLinkEvents> {
  private pendingDeepLink: LoopLinkPayload | null = null;
  private readonly log: LinkLogger;

  constructor(
    @inject(DEEP_LINK_SERVICE)
    private readonly deepLinkService: IDeepLinkRegistry,
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: IMainWindow,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    super();
    this.log = rootLogger.scope("loop-link-service");

    this.deepLinkService.registerHandler("loop", (path) =>
      this.handleLoopLink(path),
    );
  }

  private handleLoopLink(path: string): boolean {
    const loopId = decodeSegment(path.split("/")[0]);

    if (!loopId) {
      this.log.warn("Loop link missing loop id");
      return false;
    }

    const payload: LoopLinkPayload = { loopId };

    const hasListeners = this.listenerCount(LoopLinkEvent.OpenLoop) > 0;

    if (hasListeners) {
      this.log.info(`Emitting loop link event: loopId=${loopId}`);
      this.emit(LoopLinkEvent.OpenLoop, payload);
    } else {
      this.log.info(
        `Queueing loop link (renderer not ready): loopId=${loopId}`,
      );
      this.pendingDeepLink = payload;
    }

    this.log.info("Deep link focusing window", { loopId });
    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  public consumePendingDeepLink(): LoopLinkPayload | null {
    const pending = this.pendingDeepLink;
    this.pendingDeepLink = null;
    if (pending) {
      this.log.info(`Consumed pending loop link: loopId=${pending.loopId}`);
    }
    return pending;
  }
}

function decodeSegment(segment: string | undefined): string {
  if (!segment) return "";
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
