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

export const ChannelLinkEvent = {
  OpenChannel: "openChannel",
} as const;

export interface ChannelLinkPayload {
  /** Channel (folder) row id. */
  channelId: string;
  /** When present, the thread (channel-filed task) to open inside the channel. */
  taskId?: string;
}

export interface ChannelLinkEvents {
  [ChannelLinkEvent.OpenChannel]: ChannelLinkPayload;
}

/**
 * Handles channel deep links (`<scheme>://channel/{channelId}` and
 * `<scheme>://channel/{channelId}/tasks/{taskId}`, e.g. `posthog-code://…` in
 * production and `posthog-code-dev://…` in local dev). Shareable channel links
 * resolve to a web interstitial that fires this scheme, so a teammate can open
 * a channel — or a thread inside it — straight in the desktop app. The channel
 * id is a stable, rename-proof desktop file-system row id.
 *
 * Mirrors `CanvasLinkService`: queues a link that arrived before the renderer
 * was ready, and emits for links delivered while the app is already running.
 */
@injectable()
export class ChannelLinkService extends TypedEventEmitter<ChannelLinkEvents> {
  private pendingDeepLink: ChannelLinkPayload | null = null;
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
    this.log = rootLogger.scope("channel-link-service");

    this.deepLinkService.registerHandler("channel", (path) =>
      this.handleChannelLink(path),
    );
  }

  private handleChannelLink(path: string): boolean {
    const segments = path.split("/").map((segment) => decodeSegment(segment));

    const payload = parseChannelSegments(segments);
    if (!payload) {
      this.log.warn(`Channel link has unrecognised path: ${path}`);
      return false;
    }

    const hasListeners = this.listenerCount(ChannelLinkEvent.OpenChannel) > 0;

    if (hasListeners) {
      this.log.info(
        `Emitting channel link event: channelId=${payload.channelId} taskId=${payload.taskId ?? "-"}`,
      );
      this.emit(ChannelLinkEvent.OpenChannel, payload);
    } else {
      this.log.info(
        `Queueing channel link (renderer not ready): channelId=${payload.channelId} taskId=${payload.taskId ?? "-"}`,
      );
      this.pendingDeepLink = payload;
    }

    this.log.info("Deep link focusing window", payload);
    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  public consumePendingDeepLink(): ChannelLinkPayload | null {
    const pending = this.pendingDeepLink;
    this.pendingDeepLink = null;
    if (pending) {
      this.log.info(
        `Consumed pending channel link: channelId=${pending.channelId} taskId=${pending.taskId ?? "-"}`,
      );
    }
    return pending;
  }
}

// Accepts exactly `<channelId>` or `<channelId>/tasks/<taskId>` — anything else
// is rejected rather than guessed at, so a malformed link can't half-navigate.
function parseChannelSegments(segments: string[]): ChannelLinkPayload | null {
  const [channelId, kind, taskId, ...rest] = segments;
  if (!channelId) return null;
  if (kind === undefined) return { channelId };
  if (kind === "tasks" && taskId && rest.length === 0) {
    return { channelId, taskId };
  }
  return null;
}

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
