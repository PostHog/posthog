import { resolveInboxReportDetailCache } from "@posthog/core/inbox/inboxQuery";
import { resolveService } from "@posthog/di/container";
import type { SignalReport } from "@posthog/shared/types";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";

// Read inbox report detail from the React Query cache without fetching.
// Works in route loaders (outside React) via the host-bound query client.
export function getCachedInboxReportDetail(
  reportId: string,
): SignalReport | undefined {
  return resolveInboxReportDetailCache(
    resolveService<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT),
    reportId,
  );
}
