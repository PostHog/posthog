import { USAGE_MONITOR_SERVICE } from "@posthog/core/usage/identifiers";
import {
  UsageMonitorEvent,
  type UsageMonitorEvents,
  usageSnapshotOutput,
} from "@posthog/core/usage/monitor-schemas";
import type { UsageMonitorService } from "@posthog/core/usage/usage-monitor";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

function subscribe<K extends keyof UsageMonitorEvents>(event: K) {
  return publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<UsageMonitorService>(
      USAGE_MONITOR_SERVICE,
    );
    const iterable = service.toIterable(event, { signal: opts.signal });
    for await (const data of iterable) {
      yield data;
    }
  });
}

export const usageMonitorRouter = router({
  onThresholdCrossed: subscribe(UsageMonitorEvent.ThresholdCrossed),
  onUsageUpdated: subscribe(UsageMonitorEvent.UsageUpdated),
  getLatest: publicProcedure
    .output(usageSnapshotOutput)
    .query(({ ctx }) =>
      ctx.container.get<UsageMonitorService>(USAGE_MONITOR_SERVICE).getLatest(),
    ),
  refresh: publicProcedure
    .output(usageSnapshotOutput)
    .mutation(({ ctx }) =>
      ctx.container
        .get<UsageMonitorService>(USAGE_MONITOR_SERVICE)
        .refreshNow(),
    ),
});
