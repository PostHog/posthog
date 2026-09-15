import {
  type ReportImplementationState,
  reportImplementationTaskId,
} from "@posthog/core/inbox/reportImplementation";
import {
  REPORT_IMPLEMENTATION_SERVICE,
  type ReportImplementationService,
} from "@posthog/core/inbox/reportImplementationService";
import { useService } from "@posthog/di/react";
import type { SignalReport } from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { DESKTOP_INBOX_REFETCH_INTERVAL_MS } from "@posthog/ui/features/inbox/hooks/inboxPolling";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { useQuery } from "@tanstack/react-query";

export function useReportImplementationStates(reports: SignalReport[]): {
  states: Map<string, ReportImplementationState | null>;
  isLoading: boolean;
} {
  const client = useOptionalAuthenticatedClient();
  const service = useService<ReportImplementationService>(
    REPORT_IMPLEMENTATION_SERVICE,
  );
  const assignedReports = reports.filter(reportImplementationTaskId);
  const query = useQuery({
    queryKey: [
      ...taskKeys.allSummaries(),
      "inbox",
      assignedReports
        .map((report) => [
          report.id,
          report.assignee,
          report.status,
          report.implementation_pr_url,
          report.implementation_pr_merged,
        ])
        .sort((left, right) => String(left[0]).localeCompare(String(right[0]))),
    ],
    queryFn: () => {
      if (!client) throw new Error("Not authenticated");
      return service.loadStates(client, assignedReports);
    },
    enabled: !!client && assignedReports.length > 0,
    staleTime: 10_000,
    refetchInterval: DESKTOP_INBOX_REFETCH_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });
  return {
    states: query.isError
      ? service.initialStates(assignedReports, true)
      : (query.data ?? service.initialStates(assignedReports, !client)),
    isLoading: query.isLoading,
  };
}
