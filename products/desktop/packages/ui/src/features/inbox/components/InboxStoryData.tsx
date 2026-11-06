import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import type { SignalReport } from "@posthog/shared/types";
import { inboxStoryImplementations } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import type { ReportTaskData } from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";

export function InboxStoryData({
  report,
  children,
}: {
  report?: SignalReport;
  children: ReactNode;
}): ReactNode {
  const queryClient = useQueryClient();
  const [seeded, setSeeded] = useState<{
    report?: SignalReport;
    queryClient: typeof queryClient;
  } | null>(null);
  useEffect(() => {
    const storyReports = [
      ...inboxStoryImplementations.map((entry) => entry.report),
      ...(report ? [report] : []),
    ];
    const previous = new Map<readonly unknown[], unknown>();
    const seed = (queryKey: readonly unknown[], data: unknown): void => {
      previous.set(queryKey, queryClient.getQueryData(queryKey));
      queryClient.setQueryData(queryKey, data);
    };
    for (const item of Array.from(
      new Map(storyReports.map((item) => [item.id, item])).values(),
    )) {
      const task = inboxStoryImplementations.find(
        (entry) => entry.report.id === item.id,
      )?.task;
      const tasks: ReportTaskData[] = task
        ? [
            {
              task,
              purpose: "implementation",
              purposeLabel: "Implementation",
              startedAt: task.created_at,
            },
          ]
        : [];
      const tasksKey = ["inbox", "report-tasks", item.id];
      const artefactsKey = inboxReportKeys.artefacts(item.id);
      seed(tasksKey, tasks);
      seed(artefactsKey, { results: [], count: 0 });
      if (task) seed(taskDetailQuery(task.id).queryKey, task);
    }
    setSeeded({ report, queryClient });
    return () => {
      for (const [queryKey, data] of previous) {
        if (data === undefined)
          queryClient.removeQueries({ queryKey, exact: true });
        else queryClient.setQueryData(queryKey, data);
      }
    };
  }, [queryClient, report]);
  return seeded?.queryClient === queryClient && seeded.report === report
    ? children
    : null;
}
