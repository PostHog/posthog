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
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const storyReports = [
      ...inboxStoryImplementations.map((entry) => entry.report),
      ...(report ? [report] : []),
    ];
    const keys = storyReports.flatMap((item) => {
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
      queryClient.setQueryData(tasksKey, tasks);
      queryClient.setQueryData(artefactsKey, { results: [], count: 0 });
      if (task)
        queryClient.setQueryData(taskDetailQuery(task.id).queryKey, task);
      return [
        tasksKey,
        artefactsKey,
        ...(task ? [taskDetailQuery(task.id).queryKey] : []),
      ];
    });
    setReady(true);
    return () => {
      for (const queryKey of keys)
        queryClient.removeQueries({ queryKey, exact: true });
    };
  }, [queryClient, report]);
  return ready ? children : null;
}
