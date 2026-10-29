import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import type {
  SignalReportSectionCounts,
  SignalReportSectionCountsParams,
} from "@posthog/shared/types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

/**
 * Backend counts of the ready reports with and without an implementation PR,
 * under the same server-side filters as the inbox list. One request serves the
 * pull request badge, the reports badge, and the ready badge that sums them,
 * so callers that pass the same filters share it.
 */
export function useInboxSectionCounts(
  params: SignalReportSectionCountsParams,
  options: { enabled: boolean; refetchInterval: number },
) {
  return useAuthenticatedQuery<SignalReportSectionCounts>(
    inboxReportKeys.sectionCounts(params),
    (client) => client.getSignalReportSectionCounts(params),
    { ...options, refetchIntervalInBackground: false },
  );
}
