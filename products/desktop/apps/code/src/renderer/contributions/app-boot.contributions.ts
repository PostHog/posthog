import type { Contribution } from "@posthog/di/contribution";
import {
  getCurrentSessionId,
  initializePostHog,
  isFeatureFlagEnabled,
  onFeatureFlagsLoaded,
  onSessionIdChanged,
  registerAppVersion,
  registerHostInfo,
} from "@posthog/ui/shell/posthogAnalyticsImpl";
import { trpcClient } from "@renderer/trpc/client";
import { logger } from "@utils/logger";
import { injectable } from "inversify";

const log = logger.scope("app-boot");

const SESSION_STITCHING_FLAG = "desktop-web-session-stitching";

@injectable()
export class AnalyticsBootContribution implements Contribution {
  start(): void {
    void (async () => {
      if (!window.__posthogBootstrap?.sessionId) {
        let sessionId: string | undefined;
        try {
          ({ sessionId } = await trpcClient.analytics.getSessionId.query());
        } catch (error) {
          log.warn("Failed to fetch session id from main", { error });
        }
        initializePostHog(sessionId);
      }
      this.pushSessionIdToMain();
      try {
        registerAppVersion(await trpcClient.os.getAppVersion.query());
      } catch (error) {
        log.warn("Failed to register app version super property", { error });
      }
      try {
        registerHostInfo(await trpcClient.os.getHostInfo.query());
      } catch (error) {
        log.warn("Failed to register host info super properties", { error });
      }
    })();
  }

  // Main decorates outbound PostHog web links with the renderer's live session
  // id (cross-surface session stitching). The flag doubles as a remote kill
  // switch for shipped binaries: while off, main holds null and never
  // decorates. Flags load after init, so the flags-loaded hook performs the
  // initial push; onSessionIdChanged covers idle rotations and logout resets.
  private pushSessionIdToMain(): void {
    let lastPushed: string | null | undefined;
    const sync = () => {
      const sessionId = isFeatureFlagEnabled(SESSION_STITCHING_FLAG)
        ? getCurrentSessionId()
        : null;
      if (sessionId === lastPushed) {
        return;
      }
      lastPushed = sessionId;
      trpcClient.analytics.setRendererSessionId
        .mutate({ sessionId })
        .catch((error) => {
          lastPushed = undefined;
          log.warn("Failed to push session id to main", { error });
        });
    };
    onFeatureFlagsLoaded(sync);
    onSessionIdChanged(sync);
  }
}

@injectable()
export class InboxDemoDevContribution implements Contribution {
  start(): void {
    if (import.meta.env.PROD) {
      return;
    }
    void import("@posthog/ui/features/inbox/devtools/inboxDemoConsole").then(
      ({ registerInboxDemoConsoleCommand }) => {
        registerInboxDemoConsoleCommand();
      },
    );
  }
}
