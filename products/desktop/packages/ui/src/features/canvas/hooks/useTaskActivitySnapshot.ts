import { buildActivityTimeline } from "@posthog/core/canvas/activityTimeline";
import {
  type CanvasTaskActivitySnapshot,
  toCanvasTaskActivity,
} from "@posthog/core/canvas/canvasTaskActivity";
import type { Task, TaskThreadMessage } from "@posthog/shared/domain-types";
import { toActivityUserMessages } from "@posthog/ui/features/canvas/utils/activityUserMessages";
import type { buildConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { useCallback, useMemo, useRef } from "react";

type ConversationItem = ReturnType<
  typeof buildConversationItems
>["items"][number];

const NO_COMMENT_THREADS: never[] = [];

/**
 * Reads the task's activity the way the drawn timeline builds it, and returns
 * the snapshot a canvas gets from `ph.taskActivity()`.
 *
 * The reader is a callback over a ref rather than the value itself, because a
 * canvas asks whenever it wants: the request must see the newest poll, and a
 * value in the dependency list would rebuild the data bridge on every poll and
 * remount the frame.
 */
export function useTaskActivitySnapshot({
  task,
  messages,
  conversationItems,
}: {
  task: Task;
  messages: TaskThreadMessage[];
  conversationItems: ConversationItem[];
}): (limit?: number) => CanvasTaskActivitySnapshot {
  const rows = useMemo(
    () =>
      buildActivityTimeline({
        task: {
          id: task.id,
          createdAt: task.created_at,
          updatedAt: task.updated_at,
          latestRunId: task.latest_run?.id ?? null,
          latestRunStatus: task.latest_run?.status ?? null,
          latestRunPrUrl:
            typeof task.latest_run?.output?.pr_url === "string"
              ? task.latest_run.output.pr_url
              : null,
        },
        messages,
        // The panel draws no comment rows in its timeline, so the canvas that
        // replaces it is given the same population. Comments are their own tab.
        commentThreads: NO_COMMENT_THREADS,
        userMessages: toActivityUserMessages(
          conversationItems,
          task.created_at,
        ),
      }),
    [task, messages, conversationItems],
  );

  const latest = useRef({ rows, task });
  latest.current = { rows, task };

  return useCallback(
    (limit?: number) =>
      toCanvasTaskActivity({
        task: {
          id: latest.current.task.id,
          title: latest.current.task.title,
          status: latest.current.task.latest_run?.status ?? null,
          createdAt: latest.current.task.created_at,
          updatedAt: latest.current.task.updated_at,
        },
        rows: latest.current.rows,
        limit,
      }),
    [],
  );
}
