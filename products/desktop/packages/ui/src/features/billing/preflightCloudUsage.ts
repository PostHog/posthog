import { isUsageExceeded } from "@posthog/core/billing/usageDisplay";
import type { UsageOutput } from "@posthog/core/usage/schemas";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { type UsageLimitShowArgs, useUsageLimitStore } from "./usageLimitStore";

const log = logger.scope("preflight-cloud-usage");

function usageLimitArgs(usage: UsageOutput): UsageLimitShowArgs {
  // Burst-alone is the only state the earlier daily reset unblocks; both
  // exceeded or an org-bucket block wait for the sustained window.
  const bucket =
    usage.burst.exceeded && !usage.sustained.exceeded ? "burst" : "sustained";
  return { resetAt: usage[bucket].reset_at, cause: "org_limit" };
}

async function fetchUsageSnapshot(): Promise<UsageOutput | null> {
  const client = resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
  const fresh = await client.usageMonitor.refresh.mutate().catch((error) => {
    log.warn("Usage refresh failed; falling back to latest snapshot", {
      error,
    });
    return null;
  });
  if (fresh) return fresh;

  return client.usageMonitor.getLatest.query().catch((error) => {
    log.warn("Usage lookup failed; allowing cloud creation", { error });
    return null;
  });
}

/**
 * Pre-flight gate for cloud task creation. Returns false (and shows the upgrade
 * modal) when the team is over its usage limit, so no cloud task/run is created.
 *
 * Best-effort: if usage can't be fetched, returns true (fail open) — a usage
 * service hiccup must never block task creation.
 */
export async function assertCloudUsageAvailable(): Promise<boolean> {
  const usage = await fetchUsageSnapshot();
  if (usage && isUsageExceeded(usage)) {
    track(ANALYTICS_EVENTS.CLOUD_TASK_USAGE_BLOCKED, {
      bucket: usage.burst.exceeded
        ? "burst"
        : usage.sustained.exceeded
          ? "sustained"
          : null,
      is_pro: usage.is_pro,
    });
    useUsageLimitStore.getState().show(usageLimitArgs(usage));
    return false;
  }
  return true;
}
