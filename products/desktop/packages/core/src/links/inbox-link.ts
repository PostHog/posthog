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

export const InboxLinkEvent = {
  OpenReport: "openReport",
} as const;

export interface InboxLinkEvents {
  [InboxLinkEvent.OpenReport]: { reportId: string };
}

export interface PendingInboxDeepLink {
  reportId: string;
}

@injectable()
export class InboxLinkService extends TypedEventEmitter<InboxLinkEvents> {
  private pendingDeepLink: PendingInboxDeepLink | null = null;
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
    this.log = rootLogger.scope("inbox-link-service");

    this.deepLinkService.registerHandler("inbox", (path) =>
      this.handleInboxLink(path),
    );
  }

  private handleInboxLink(path: string): boolean {
    const reportId = path.split("/")[0];

    if (!reportId) {
      this.log.warn("Inbox link missing report ID");
      return false;
    }

    const hasListeners = this.listenerCount(InboxLinkEvent.OpenReport) > 0;

    if (hasListeners) {
      this.log.info(`Emitting inbox link event: reportId=${reportId}`);
      this.emit(InboxLinkEvent.OpenReport, { reportId });
    } else {
      this.log.info(
        `Queueing inbox link (renderer not ready): reportId=${reportId}`,
      );
      this.pendingDeepLink = { reportId };
    }

    this.log.info("Deep link focusing window", { reportId });
    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  public consumePendingDeepLink(): PendingInboxDeepLink | null {
    const pending = this.pendingDeepLink;
    this.pendingDeepLink = null;
    if (pending) {
      this.log.info(
        `Consumed pending inbox link: reportId=${pending.reportId}`,
      );
    }
    return pending;
  }
}
