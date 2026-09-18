import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { INBOX_REFETCH_INTERVAL_MS } from "@posthog/core/inbox/reportFiltering";
import {
  deriveReportImplementationState,
  type ReportImplementationState,
  reportImplementationTaskId,
} from "@posthog/core/inbox/reportImplementation";
import type { SignalReport } from "@posthog/shared/domain-types";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useRef } from "react";
import { useAuthStore } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { inboxKeys } from "./useInboxReports";

type ImplementationTask = Parameters<typeof deriveReportImplementationState>[1];

const COMPLETED_TASK_BATCH = 10;
const COMPLETED_TASK_TTL_MS = 5 * 60_000;

interface CachedTask {
  version: string;
  expiresAt: number;
  task: Promise<ImplementationTask>;
}

export function collectTaskIds(reports: SignalReport[]): string[] {
  const ids = new Set<string>();
  for (const report of reports) {
    const id = reportImplementationTaskId(report);
    if (id) ids.add(id);
  }
  return [...ids].sort();
}

// Summaries omit PR output for completed tasks, so pull the detail once per
// (task, latest_run) tuple. Callers reuse the same cache across renders.
export async function loadImplementationTasks(
  client: Pick<PostHogAPIClient, "getTaskSummaries" | "getTask">,
  taskIds: string[],
  completedCache: Map<string, CachedTask>,
): Promise<Map<string, ImplementationTask>> {
  if (taskIds.length === 0) return new Map();
  const summaries = await client.getTaskSummaries(taskIds);
  const tasks = new Map<string, ImplementationTask>(
    summaries.map((summary) => [
      summary.id,
      {
        latest_run: summary.latest_run && {
          status: summary.latest_run.status,
          output: {
            pr_url: summary.latest_run.pr_url,
            pr_state: summary.latest_run.pr_state,
          },
        },
      },
    ]),
  );
  const completed = summaries.filter(
    (summary) =>
      summary.latest_run?.status === "completed" &&
      (summary.latest_run.pr_url === undefined ||
        summary.latest_run.pr_state === undefined),
  );
  for (
    let offset = 0;
    offset < completed.length;
    offset += COMPLETED_TASK_BATCH
  ) {
    const batch = completed.slice(offset, offset + COMPLETED_TASK_BATCH);
    await Promise.all(
      batch.map(async (summary) => {
        const version = `${summary.updated_at}:${summary.latest_run?.id}`;
        const cached = completedCache.get(summary.id);
        let promise: Promise<ImplementationTask>;
        if (cached?.version === version && cached.expiresAt > Date.now()) {
          promise = cached.task;
        } else {
          promise = client.getTask(summary.id);
          completedCache.set(summary.id, {
            version,
            expiresAt: Date.now() + COMPLETED_TASK_TTL_MS,
            task: promise,
          });
        }
        try {
          tasks.set(summary.id, await promise);
        } catch {
          completedCache.delete(summary.id);
          tasks.delete(summary.id);
        }
      }),
    );
  }
  const alive = new Set(taskIds);
  for (const key of completedCache.keys()) {
    if (!alive.has(key)) completedCache.delete(key);
  }
  return tasks;
}

export function deriveStates(
  reports: SignalReport[],
  tasks: Map<string, ImplementationTask> | undefined,
  succeeded: boolean,
): Map<string, ReportImplementationState | null> {
  const map = new Map<string, ReportImplementationState | null>();
  for (const report of reports) {
    const taskId = reportImplementationTaskId(report);
    const task = taskId ? tasks?.get(taskId) : undefined;
    const lookupFailed = !!taskId && !task && succeeded;
    map.set(
      report.id,
      deriveReportImplementationState(report, task, lookupFailed),
    );
  }
  return map;
}

export function useReportImplementationStates(
  reports: SignalReport[],
): Map<string, ReportImplementationState | null> {
  const { projectId, oauthAccessToken } = useAuthStore();
  const taskIds = useMemo(() => collectTaskIds(reports), [reports]);
  const completedCache = useRef<Map<string, CachedTask>>(new Map());

  const query = useQuery<Map<string, ImplementationTask>>({
    queryKey: [...inboxKeys.all, "implementation-tasks", taskIds],
    queryFn: () =>
      loadImplementationTasks(
        getPostHogApiClient(),
        taskIds,
        completedCache.current,
      ),
    enabled: !!projectId && !!oauthAccessToken && taskIds.length > 0,
    refetchInterval: INBOX_REFETCH_INTERVAL_MS,
    placeholderData: keepPreviousData,
  });

  const succeeded = query.isSuccess && !query.isFetching;

  return useMemo(
    () => deriveStates(reports, query.data, succeeded),
    [reports, query.data, succeeded],
  );
}
