import {
  buildCreatePrReportPrompt,
  canCreateImplementationPr,
} from "@posthog/core/inbox/reportActions";
import type {
  SignalReport,
  SignalReportArtefactsResponse,
  SignalReportSignalsResponse,
  SignalReportsResponse,
} from "@posthog/shared/domain-types";
import {
  type QueryClient,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { type Href, router } from "expo-router";
import { useCallback, useMemo } from "react";
import { useAuth } from "@/lib/auth";
import { getClient } from "@/lib/client";
import { currentRunConfig } from "@/lib/composer";
import {
  hasOpenImplementationPr,
  type ReportFilter,
  reportFilterParams,
} from "@/lib/reportFilters";
import {
  markReadOptimistically,
  type ReadStateResult,
  type ReportReadStates,
  restoreReadState,
  summarizeReadStates,
} from "@/lib/reportReadState";
import { fetchHasLiveImplementationTask } from "@/lib/reportTasks";
import { useSessions } from "@/lib/session";

export const reportKeys = {
  all: ["reports"] as const,
  list: ["reports", "list"] as const,
  detail: (id: string) => ["reports", "detail", id] as const,
  read: (id: string) => ["reports", "read", id] as const,
  signals: (id: string) => ["reports", id, "signals"] as const,
  artefacts: (id: string) => ["reports", id, "artefacts"] as const,
  liveTask: (id: string) => ["reports", id, "live-task"] as const,
};

// Defaults to the reports a person can act on right now.
export function useReports(search = "", filter: ReportFilter = "attention") {
  const session = useAuth((s) => s.session);
  const key = [...reportKeys.list, filter];
  return useQuery({
    queryKey: search ? [...key, "search", search] : key,
    queryFn: () =>
      getClient().getSignalReports({
        ...reportFilterParams(filter),
        limit: 100,
        search: search || undefined,
      }),
    enabled: !!session,
    refetchInterval: 60_000,
    select: (page) => {
      if (filter === "attention") {
        return page.results.filter((report) =>
          canCreateImplementationPr(report),
        );
      }
      if (filter === "pull-requests") {
        return page.results.filter(hasOpenImplementationPr);
      }
      return page.results;
    },
  });
}

// Seeded from whichever list already holds the report, so the screen opens
// with content and refreshes behind it.
export function useReport(reportId: string) {
  const queryClient = useQueryClient();
  const cached = () => {
    for (const [key, page] of queryClient.getQueriesData<SignalReportsResponse>(
      { queryKey: reportKeys.list },
    )) {
      const report = page?.results.find((item) => item.id === reportId);
      if (report) return { report, key };
    }
    return undefined;
  };
  return useQuery({
    queryKey: reportKeys.detail(reportId),
    queryFn: () => getClient().getSignalReport(reportId),
    enabled: !!reportId,
    initialData: () => cached()?.report,
    initialDataUpdatedAt: () => {
      const key = cached()?.key;
      return key ? queryClient.getQueryState(key)?.dataUpdatedAt : undefined;
    },
  });
}

export function useReportSignals(reportId: string | null) {
  return useQuery<SignalReportSignalsResponse>({
    queryKey: reportKeys.signals(reportId ?? ""),
    queryFn: () => getClient().getSignalReportSignals(reportId ?? ""),
    enabled: !!reportId,
    staleTime: 5 * 60_000,
  });
}

export function useReportArtefacts(reportId: string | null) {
  return useQuery<SignalReportArtefactsResponse>({
    queryKey: reportKeys.artefacts(reportId ?? ""),
    queryFn: () => getClient().getSignalReportArtefacts(reportId ?? ""),
    enabled: !!reportId,
    staleTime: 5 * 60_000,
  });
}

export function useHasLiveImplementationTask(reportId: string) {
  return useQuery({
    queryKey: reportKeys.liveTask(reportId),
    queryFn: () => fetchHasLiveImplementationTask(getClient(), reportId),
    enabled: !!reportId,
  });
}

// Takes an acted-on report out of every loaded list at once, wherever the
// action came from. A failed action refetches and brings it back.
async function dropFromLists(
  queryClient: QueryClient,
  reportId: string,
): Promise<void> {
  await queryClient.cancelQueries({ queryKey: reportKeys.list });
  queryClient.setQueriesData<SignalReportsResponse>(
    { queryKey: reportKeys.list },
    (page) =>
      page && {
        ...page,
        results: page.results.filter((report) => report.id !== reportId),
      },
  );
}

export function useDismissReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (reportId: string) =>
      getClient().updateSignalReportState(reportId, { state: "suppressed" }),
    onMutate: (reportId) => dropFromLists(queryClient, reportId),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: reportKeys.all }),
  });
}

// Tasks created for a report whose run failed to start. A retry reuses the
// task so the report does not collect duplicate implementation tasks.
const unstartedTasks = new Map<string, string>();

export function resetUnstartedReportTasks(): void {
  unstartedTasks.clear();
}

// Swipe right: open a task on the report's repo and start the agent on it.
export function useStartReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (report: SignalReport) => {
      const client = getClient();
      const prompt = buildCreatePrReportPrompt({ reportId: report.id });
      let taskId = unstartedTasks.get(report.id);
      if (!taskId) {
        if (await fetchHasLiveImplementationTask(client, report.id)) {
          throw new Error("This report already has a task in progress.");
        }
        // The server picks the repository from the report's repo selection.
        const task = await client.createTask({
          description: prompt,
          title: (report.title ?? "Signal report").slice(0, 255),
          origin_product: "signal_report",
          signal_report: report.id,
          signal_report_task_relationship: "implementation",
        });
        taskId = task.id;
        unstartedTasks.set(report.id, taskId);
      }
      const started = await client.runTaskInCloud(taskId, undefined, {
        pendingUserMessage: prompt,
        runSource: "signal_report",
        signalReportId: report.id,
        ...currentRunConfig(),
      });
      unstartedTasks.delete(report.id);
      return started;
    },
    onMutate: (report) => dropFromLists(queryClient, report.id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: reportKeys.all });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

// Opens the chat at once with the report prompt in it (the same pending
// pattern as the new-chat screen), then re-keys it to the real task id.
export function useStartReportTask() {
  const start = useStartReport();
  const run = (
    report: SignalReport,
    open: (href: Href) => void,
  ): Promise<void> => {
    const tempId = `new-${Date.now()}`;
    const prompt = buildCreatePrReportPrompt({ reportId: report.id });
    const { startPending, adopt, failPending } = useSessions.getState();
    startPending(tempId, prompt, `local-${Date.now()}`);
    open({ pathname: "/(drawer)/task/[id]", params: { id: tempId } });
    // mutateAsync, not mutate callbacks: the caller may unmount on navigation.
    return start.mutateAsync(report).then(
      (task) => {
        adopt(tempId, task);
        router.replace({
          pathname: "/(drawer)/task/[id]",
          params: { id: task.id },
        });
      },
      (error: Error) => {
        failPending(tempId, error.message);
        throw error;
      },
    );
  };
  return { start: run, isPending: start.isPending };
}

// Read state lives on the server, so a report read on one device is read on
// all of them. The client batches the per-report lookups into one request.
export function useReportReadStates(
  reportIds: readonly string[],
  { enabled = true }: { enabled?: boolean } = {},
): ReportReadStates {
  const results = useQueries({
    queries: reportIds.map((id) => ({
      queryKey: reportKeys.read(id),
      queryFn: () => getClient().getReportReadState(id),
      enabled,
      // Unread needs a fetch after mount, so every new screen (and the drawer
      // when it opens) asks the server again even if the cache is recent.
      staleTime: 0,
      refetchInterval: enabled ? 30_000 : false,
    })),
    combine: pickReadStates,
  });
  return useMemo(
    () => summarizeReadStates(reportIds, results),
    [reportIds, results],
  );
}

function pickReadStates(results: ReadStateResult[]): ReadStateResult[] {
  return results.map(({ data, isError, isFetchedAfterMount }) => ({
    data,
    isError,
    isFetchedAfterMount,
  }));
}

export function useMarkReportRead(): (reportId: string) => void {
  const queryClient = useQueryClient();
  const { mutate } = useMutation({
    mutationFn: (reportId: string) =>
      getClient().getReportReadStates([reportId], true),
    onMutate: async (reportId) => ({
      previous: await markReadOptimistically(
        queryClient,
        reportKeys.read(reportId),
      ),
    }),
    onSuccess: (states, reportId) =>
      queryClient.setQueryData(
        reportKeys.read(reportId),
        states[reportId] === true,
      ),
    onError: (_error, reportId, context) =>
      restoreReadState(
        queryClient,
        reportKeys.read(reportId),
        context?.previous,
      ),
  });
  return useCallback(
    (reportId: string) => {
      if (queryClient.getQueryData(reportKeys.read(reportId)) === true) return;
      mutate(reportId);
    },
    [queryClient, mutate],
  );
}
