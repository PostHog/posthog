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

export const ScoutLinkEvent = {
  OpenScout: "openScout",
} as const;

export interface ScoutLinkPayload {
  /** Route slug for the scout (e.g. "error-tracking"). */
  skillSlug: string;
  /** Emission id to expand and scroll to, if the link carried one. */
  findingId?: string;
}

export interface ScoutLinkEvents {
  [ScoutLinkEvent.OpenScout]: ScoutLinkPayload;
}

@injectable()
export class ScoutLinkService extends TypedEventEmitter<ScoutLinkEvents> {
  private pendingDeepLink: ScoutLinkPayload | null = null;
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
    this.log = rootLogger.scope("scout-link-service");

    this.deepLinkService.registerHandler("scout", (path, searchParams) =>
      this.handleScoutLink(path, searchParams),
    );
  }

  private handleScoutLink(
    path: string,
    searchParams: URLSearchParams,
  ): boolean {
    const skillSlug = decodeSegment(path.split("/")[0]);

    if (!skillSlug) {
      this.log.warn("Scout link missing skill slug");
      return false;
    }

    const findingId = searchParams.get("finding") ?? undefined;
    const payload: ScoutLinkPayload = { skillSlug, findingId };

    const hasListeners = this.listenerCount(ScoutLinkEvent.OpenScout) > 0;

    if (hasListeners) {
      this.log.info(
        `Emitting scout link event: skillSlug=${skillSlug} findingId=${findingId ?? "(none)"}`,
      );
      this.emit(ScoutLinkEvent.OpenScout, payload);
    } else {
      this.log.info(
        `Queueing scout link (renderer not ready): skillSlug=${skillSlug}`,
      );
      this.pendingDeepLink = payload;
    }

    this.log.info("Deep link focusing window", { skillSlug });
    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  public consumePendingDeepLink(): ScoutLinkPayload | null {
    const pending = this.pendingDeepLink;
    this.pendingDeepLink = null;
    if (pending) {
      this.log.info(
        `Consumed pending scout link: skillSlug=${pending.skillSlug}`,
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
