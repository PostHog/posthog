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

export const ApprovalLinkEvent = {
  OpenApproval: "openApproval",
} as const;

export interface ApprovalLinkPayload {
  /** Agent tool-approval request id. */
  requestId: string;
  /**
   * Agent slug from `?agent=<slug>`, when present. Lets the renderer address
   * the slug-routed ingress directly and decide the approval in a modal (works
   * from any project). Null on legacy links → fall back to the fleet inbox.
   */
  agent: string | null;
}

export interface ApprovalLinkEvents {
  [ApprovalLinkEvent.OpenApproval]: ApprovalLinkPayload;
}

/**
 * Handles agent approval deep links (`<scheme>://approval/{requestId}`, e.g.
 * `posthog-code://approval/ar_...` in production and `posthog-code-dev://…` in
 * local dev). The agent-runner emits these on a gated tool call so non-PostHog-Code
 * clients (Slack, MCP) can open the approval in the desktop app. The request id
 * alone resolves the approval in the fleet inbox, so the link carries nothing else.
 *
 * Mirrors `ScoutLinkService`: queues a link that arrived before the renderer was
 * ready, and emits for links delivered while the app is already running.
 */
@injectable()
export class ApprovalLinkService extends TypedEventEmitter<ApprovalLinkEvents> {
  private pendingDeepLink: ApprovalLinkPayload | null = null;
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
    this.log = rootLogger.scope("approval-link-service");

    this.deepLinkService.registerHandler("approval", (path, searchParams) =>
      this.handleApprovalLink(path, searchParams),
    );
  }

  private handleApprovalLink(
    path: string,
    searchParams: URLSearchParams,
  ): boolean {
    const requestId = decodeSegment(path.split("/")[0]);

    if (!requestId) {
      this.log.warn("Approval link missing request id");
      return false;
    }

    const payload: ApprovalLinkPayload = {
      requestId,
      agent: searchParams.get("agent") || null,
    };

    const hasListeners = this.listenerCount(ApprovalLinkEvent.OpenApproval) > 0;

    if (hasListeners) {
      this.log.info(`Emitting approval link event: requestId=${requestId}`);
      this.emit(ApprovalLinkEvent.OpenApproval, payload);
    } else {
      this.log.info(
        `Queueing approval link (renderer not ready): requestId=${requestId}`,
      );
      this.pendingDeepLink = payload;
    }

    this.log.info("Deep link focusing window", { requestId });
    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  public consumePendingDeepLink(): ApprovalLinkPayload | null {
    const pending = this.pendingDeepLink;
    this.pendingDeepLink = null;
    if (pending) {
      this.log.info(
        `Consumed pending approval link: requestId=${pending.requestId}`,
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
