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
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { DESKTOP_INBOX_REFETCH_INTERVAL_MS } from "@posthog/ui/features/inbox/hooks/inboxPolling";
import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";

/**
 * This cache holds a report-to-state map, not a `TaskSummaryDTO[]`, so it owns
 * a root of its own. Under the task-summaries prefix the rename and auto-title
 * writers would map over it as an array and throw. Task changes that must
 * refresh these states invalidate this root beside that prefix.
 */
export const reportImplementationStatesQueryRoot = [
  "report-implementation-states",
] as const;

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
      ...reportImplementationStatesQueryRoot,
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
    // Task state belongs to the signed-in user, so logout and a project switch
    // have to drop it: clearAuthScopedQueries only removes queries carrying
    // this meta. The query stays hand-rolled rather than going through
    // useAuthenticatedQuery because that helper spreads caller options over its
    // own enabled, which would drop the client gate above and fire a request
    // that is certain to fail while signed out.
    meta: AUTH_SCOPED_QUERY_META,
    staleTime: 10_000,
    refetchInterval: DESKTOP_INBOX_REFETCH_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });
  // Every report that gains or finishes a task rewrites the key above, so the
  // next fetch starts empty. Reports already checked keep the state they had
  // rather than going back to "checking", which would move the triage queue
  // under the reader for the length of the fetch.
  const resolved = useRef<Map<string, ReportImplementationState | null>>(
    new Map(),
  );
  if (query.data) resolved.current = query.data;
  return {
    states: query.isError
      ? service.initialStates(assignedReports, true)
      : (query.data ??
        service.pendingStates(assignedReports, resolved.current, !client)),
    isLoading: query.isLoading,
  };
}
