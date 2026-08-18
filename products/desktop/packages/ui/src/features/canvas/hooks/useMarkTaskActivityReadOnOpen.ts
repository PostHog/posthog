import { useEffect } from "react";
import { useMarkTaskActivityRead } from "./useMarkTaskActivityRead";

/**
 * Opening a task counts as reading it: clears the task's activity-feed row
 * (server read state and the cached feed) once per task the surface shows.
 */
export function useMarkTaskActivityReadOnOpen(
  taskId: string | undefined,
): void {
  const { mutate: markTasksRead } = useMarkTaskActivityRead();
  useEffect(() => {
    if (!taskId) return;
    markTasksRead([{ task_id: taskId, seen_before: new Date().toISOString() }]);
  }, [taskId, markTasksRead]);
}
