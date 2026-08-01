import { formatResetTime } from "@posthog/core/billing/usageDisplay";
import type { Contribution } from "@posthog/di/contribution";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { inject, injectable } from "inversify";
import { toast } from "../../primitives/toast";
import { openSettings } from "../settings/hooks/useOpenSettings";
import { useUsageLimitStore } from "./usageLimitStore";

const openPlanUsage = () => {
  openSettings("plan-usage");
};

@injectable()
export class BillingContribution implements Contribution {
  constructor(
    @inject(ROOT_LOGGER)
    private readonly logger: RootLogger,
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
  ) {}

  start(): void {
    this.hostClient.usageMonitor.onThresholdCrossed.subscribe(undefined, {
      onData: (event) => {
        const resetLabel = formatResetTime(event.resetAt);

        // The monitor only emits thresholds for confirmed free-tier orgs, so
        // the free-usage framing (and the org_limit cause) is always right.
        if (event.threshold === 100) {
          if (event.userIsActive) {
            useUsageLimitStore
              .getState()
              .show({ resetAt: event.resetAt, cause: "org_limit" });
            return;
          }
          toast.error("Free usage used up", {
            id: `usage-threshold-${event.bucket}-100`,
            description: resetLabel,
          });
          return;
        }

        const period = event.bucket === "burst" ? "daily" : "monthly";
        toast.warning(
          `You've used ${Math.round(event.usedPercent)}% of your ${period} free usage`,
          {
            id: `usage-threshold-${event.bucket}-${event.threshold}`,
            description: resetLabel,
            action: { label: "View usage", onClick: openPlanUsage },
            duration: 10_000,
          },
        );
      },
      onError: (error) => {
        this.logger.error("Usage threshold subscription error", { error });
      },
    });
  }
}
