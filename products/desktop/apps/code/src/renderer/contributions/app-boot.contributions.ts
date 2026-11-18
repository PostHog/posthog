import type { Contribution } from "@posthog/di/contribution";
import {
  type Adapter,
  CLAUDE_OWN_SUBSCRIPTION_FLAG,
  CODEX_OWN_SUBSCRIPTION_FLAG,
} from "@posthog/shared";
import {
  registerSubscriptionAtBoot,
  type SubscriptionStatus,
} from "@posthog/ui/features/settings/adapterSubscription";
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

const SUBSCRIPTION_BOOT: {
  adapter: Adapter;
  flag: string;
  fetchStatus: () => Promise<SubscriptionStatus>;
}[] = [
  {
    adapter: "codex",
    flag: CODEX_OWN_SUBSCRIPTION_FLAG,
    fetchStatus: () => trpcClient.agent.codexSubscriptionStatus.query(),
  },
  {
    adapter: "claude",
    flag: CLAUDE_OWN_SUBSCRIPTION_FLAG,
    fetchStatus: () => trpcClient.agent.claudeSubscriptionStatus.query(),
  },
];

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
      for (const { adapter, flag, fetchStatus } of SUBSCRIPTION_BOOT) {
        try {
          await registerSubscriptionAtBoot(
            adapter,
            fetchStatus,
            posthogFeatureFlags.isEnabled(flag) || import.meta.env.DEV,
          );
        } catch (error) {
          log.warn(
            `Failed to register ${adapter} subscription super properties`,
            { error },
          );
        }
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
