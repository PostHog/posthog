import { useCallback, useEffect, useRef } from "react";
import { useMarkTaskActivityRead } from "./useMarkTaskActivityRead";
import { useTaskActivity } from "./useTaskActivity";

/**
 * Opening a task counts as reading it: clears the task's activity-feed row
 * (server read state and the cached feed) when the surface mounts, and keeps
 * it clear while the task stays on a focused screen. Activity that lands
 * while the window is unfocused stays unread until focus returns, matching
 * how the notification bus only births signals read for a focused viewer.
 *
 * `seen_before` is the newer of "now" and the row's own `activity_at`: rows
 * are stamped by the server clock, so a lagging client clock alone must not
 * leave the row it is clearing out of range.
 */
export function useMarkTaskActivityReadOnOpen(
  taskId: string | undefined,
): void {
  const { items } = useTaskActivity({ enabled: false });
  const { mutate: markTasksRead } = useMarkTaskActivityRead();
  const row = taskId ? items.find((item) => item.taskId === taskId) : undefined;
  const latestActivityAt = row?.activityAt;
  const hasUnread = row?.isUnread ?? false;
  const latestRef = useRef(latestActivityAt);
  latestRef.current = latestActivityAt;
  const marked = useRef<{ taskId: string; seenBefore: string } | null>(null);

  const mark = useCallback(() => {
    if (!taskId) return;
    const latest = latestRef.current;
    const last = marked.current;
    if (
      last?.taskId === taskId &&
      (!latest || Date.parse(latest) <= Date.parse(last.seenBefore))
    ) {
      return;
    }
    const now = new Date().toISOString();
    const seenBefore =
      latest && Date.parse(latest) > Date.parse(now) ? latest : now;
    marked.current = { taskId, seenBefore };
    markTasksRead([{ task_id: taskId, seen_before: seenBefore }]);
  }, [taskId, markTasksRead]);

  useEffect(() => {
    mark();
  }, [mark]);

  useEffect(() => {
    if (!hasUnread) return;
    if (document.hasFocus()) {
      mark();
      return;
    }
    window.addEventListener("focus", mark);
    return () => window.removeEventListener("focus", mark);
  }, [hasUnread, mark]);
}
