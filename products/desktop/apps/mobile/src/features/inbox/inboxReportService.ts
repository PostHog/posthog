import { InboxReportService } from "@posthog/core/inbox/inboxReportService";
import type { QueryClient } from "@tanstack/react-query";
import { userQueryOptions } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

export function createInboxReportService(queryClient: QueryClient) {
  return new InboxReportService(
    () => queryClient.fetchQuery({ ...userQueryOptions, retry: false }),
    (params) => getPostHogApiClient().getSignalReports(params),
  );
}
