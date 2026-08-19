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

export const UsageLinkEvent = {
  OpenUsage: "openUsage",
} as const;

export interface UsageLinkPayload {
  /**
   * Settings category to open. Defaults to `plan-usage` (the Plan & usage
   * page) when the link carries no category, e.g. `posthog-code://usage`.
   * A link like `posthog-code://usage/agents` overrides it.
   */
  category: string;
}

export interface UsageLinkEvents {
  [UsageLinkEvent.OpenUsage]: UsageLinkPayload;
}

const DEFAULT_CATEGORY = "plan-usage";

@injectable()
export class UsageLinkService extends TypedEventEmitter<UsageLinkEvents> {
  private pendingDeepLink: UsageLinkPayload | null = null;
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
    this.log = rootLogger.scope("usage-link-service");

    this.deepLinkService.registerHandler("usage", (path) =>
      this.handleUsageLink(path),
    );
  }

  private handleUsageLink(path: string): boolean {
    const category = decodeSegment(path.split("/")[0]) || DEFAULT_CATEGORY;

    const payload: UsageLinkPayload = { category };

    const hasListeners = this.listenerCount(UsageLinkEvent.OpenUsage) > 0;

    if (hasListeners) {
      this.log.info(`Emitting usage link event: category=${category}`);
      this.emit(UsageLinkEvent.OpenUsage, payload);
    } else {
      this.log.info(
        `Queueing usage link (renderer not ready): category=${category}`,
      );
      this.pendingDeepLink = payload;
    }

    this.log.info("Deep link focusing window", { category });
    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  public consumePendingDeepLink(): UsageLinkPayload | null {
    const pending = this.pendingDeepLink;
    this.pendingDeepLink = null;
    if (pending) {
      this.log.info(
        `Consumed pending usage link: category=${pending.category}`,
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
