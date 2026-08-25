import type { Contribution } from "@posthog/di/contribution";
import {
  initializePostHog,
  registerAppVersion,
  registerHostInfo,
} from "@posthog/ui/shell/posthogAnalyticsImpl";
import { trpcClient } from "@renderer/trpc/client";
import { logger } from "@utils/logger";
import { injectable } from "inversify";

const log = logger.scope("app-boot");

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
