import {
  deriveReportImplementationState,
  type ReportImplementationState,
  reportImplementationTaskId,
} from "@posthog/core/inbox/reportImplementation";
import type { SignalReport } from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { DESKTOP_INBOX_REFETCH_INTERVAL_MS } from "@posthog/ui/features/inbox/hooks/inboxPolling";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQueries } from "@tanstack/react-query";

export function useReportImplementationStates(reports: SignalReport[]): {
  states: Map<string, ReportImplementationState | null>;
  isLoading: boolean;
} {
  const client = useOptionalAuthenticatedClient();
  const assignedReports = reports.filter(reportImplementationTaskId);
  const queries = useQueries({
    queries: assignedReports.map((report) => {
      const taskId = reportImplementationTaskId(report) as string;
      return {
        ...taskDetailQuery(taskId),
        queryFn: async () => {
          if (!client) throw new Error("Not authenticated");
          return client.getTask(taskId);
        },
        enabled: !!client,
        staleTime: 10_000,
        refetchInterval: DESKTOP_INBOX_REFETCH_INTERVAL_MS,
        refetchIntervalInBackground: false,
      };
    }),
  });
  return {
    states: new Map(
      assignedReports.map((report, index) => [
        report.id,
        deriveReportImplementationState(
          report,
          queries[index].data,
          queries[index].isError,
        ),
      ]),
    ),
    isLoading: queries.some((query) => query.isLoading),
  };
}
