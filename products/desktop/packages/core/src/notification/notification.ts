import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import type { NotificationTarget } from "@posthog/platform/notifications";
import { type INotifier, NOTIFIER_SERVICE } from "@posthog/platform/notifier";
import { inject, injectable } from "inversify";
import { OPEN_TARGET_LINK_SERVICE } from "../links/identifiers";
import type { OpenTargetLinkService } from "../links/open-target-link";

@injectable()
export class NotificationService {
  private readonly log: ScopedLogger;

  constructor(
    @inject(OPEN_TARGET_LINK_SERVICE)
    private readonly openTargetLink: OpenTargetLinkService,
    @inject(NOTIFIER_SERVICE)
    private readonly notifier: INotifier,
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: IMainWindow,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    this.log = logger.scope("notification");
  }

  send(
    title: string,
    body: string,
    silent: boolean,
    target?: NotificationTarget,
  ): void {
    if (!this.notifier.isSupported()) {
      this.log.warn("Notifications not supported on this platform");
      return;
    }

    this.notifier.notify({
      title,
      body,
      silent,
      onClick: () => {
        this.log.info("Notification clicked, focusing window", {
          title,
          target: target?.kind,
        });
        if (this.mainWindow.isMinimized()) {
          this.mainWindow.restore();
        }
        this.mainWindow.focus();

        if (target) {
          // Window focus is handled inside open(); we still focus above so a
          // targetless notification raises the app too.
          this.openTargetLink.open(target);
          this.log.info("Notification clicked, navigating to target", {
            kind: target.kind,
          });
        }
      },
    });
    this.log.info("Notification sent", { title, body, silent, target });
  }

  // `count` is the caller's source of truth (e.g. the renderer's unread task
  // activity count) — this is a thin forward, not a running tally.
  setBadgeCount(count: number): void {
    this.notifier.setBadgeCount(count);
    this.log.info("Dock badge count set", { count });
  }

  bounceDock(): void {
    this.notifier.requestAttention();
    this.log.info("Dock bounce triggered");
  }
}
