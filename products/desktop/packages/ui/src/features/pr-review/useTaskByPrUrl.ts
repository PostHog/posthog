import { readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

/**
 * Find the task whose cloud run opened a given PR URL, so the PR view can
 * reach the run's Temporal workflow for babysit attention. Returns the first
 * matching task (first-created-first-listed) or undefined.
 */
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
