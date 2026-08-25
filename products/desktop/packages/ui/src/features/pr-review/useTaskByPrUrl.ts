import { readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

export function useTaskByPrUrl(prUrl: string | undefined): Task | undefined {
  const { data: tasks = [] } = useTasks();
  return useMemo(
    () =>
      prUrl
        ? tasks.find((task) =>
            readPrUrls(task.latest_run?.output).includes(prUrl),
          )
        : undefined,
    [tasks, prUrl],
  );
}
