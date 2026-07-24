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

export const CanvasLinkEvent = {
  OpenCanvas: "openCanvas",
} as const;

export interface CanvasLinkPayload {
  /** Channel (folder) row id the canvas lives under. */
  channelId: string;
  /** Dashboard row id of the canvas. */
  dashboardId: string;
}

export interface CanvasLinkEvents {
  [CanvasLinkEvent.OpenCanvas]: CanvasLinkPayload;
}

/**
 * Handles canvas deep links (`<scheme>://canvas/{channelId}/{dashboardId}`, e.g.
 * `posthog-code://…` in production and `posthog-code-dev://…` in local dev).
 * Shareable canvas links resolve to a web interstitial that fires this scheme,
 * so a teammate can open a canvas straight in the desktop app. Both ids are
 * stable, rename-proof desktop file-system row ids.
 *
 * Mirrors `InboxLinkService`: queues a link that arrived before the renderer was
 * ready, and emits for links delivered while the app is already running.
 */
@injectable()
export class CanvasLinkService extends TypedEventEmitter<CanvasLinkEvents> {
  private pendingDeepLink: CanvasLinkPayload | null = null;
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
    this.log = rootLogger.scope("canvas-link-service");

    this.deepLinkService.registerHandler("canvas", (path) =>
      this.handleCanvasLink(path),
    );
  }

  private handleCanvasLink(path: string): boolean {
    const [channelId, dashboardId] = path
      .split("/")
      .map((segment) => decodeSegment(segment));

    if (!channelId || !dashboardId) {
      this.log.warn("Canvas link missing channel or dashboard id");
      return false;
    }

    const payload: CanvasLinkPayload = { channelId, dashboardId };

    const hasListeners = this.listenerCount(CanvasLinkEvent.OpenCanvas) > 0;

    if (hasListeners) {
      this.log.info(
        `Emitting canvas link event: channelId=${channelId} dashboardId=${dashboardId}`,
      );
      this.emit(CanvasLinkEvent.OpenCanvas, payload);
    } else {
      this.log.info(
        `Queueing canvas link (renderer not ready): channelId=${channelId} dashboardId=${dashboardId}`,
      );
      this.pendingDeepLink = payload;
    }

    this.log.info("Deep link focusing window", { channelId, dashboardId });
    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  public consumePendingDeepLink(): CanvasLinkPayload | null {
    const pending = this.pendingDeepLink;
    this.pendingDeepLink = null;
    if (pending) {
      this.log.info(
        `Consumed pending canvas link: channelId=${pending.channelId} dashboardId=${pending.dashboardId}`,
      );
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
