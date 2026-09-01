import type { Contribution } from "@posthog/di/contribution";
import { CODEX_OWN_SUBSCRIPTION_FLAG } from "@posthog/shared";
import { registerCodexSubscriptionAtBoot } from "@posthog/ui/features/settings/useCodexSubscription";
import {
  initializePostHog,
  posthogFeatureFlags,
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
      try {
        const codexFlagEnabled =
          posthogFeatureFlags.isEnabled(CODEX_OWN_SUBSCRIPTION_FLAG) ||
          import.meta.env.DEV;
        await registerCodexSubscriptionAtBoot(
          () => trpcClient.agent.codexSubscriptionStatus.query(),
          codexFlagEnabled,
        );
      } catch (error) {
        log.warn("Failed to register codex subscription super properties", {
          error,
        });
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
