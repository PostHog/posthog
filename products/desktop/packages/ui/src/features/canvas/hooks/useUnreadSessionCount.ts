import { countSessionsByChannel } from "@posthog/core/canvas/channelUnread";
import {
  isTaskUnread,
  readRunMode,
} from "@posthog/core/sidebar/buildSidebarData";
import { taskActivityAt } from "@posthog/core/tasks/taskActivity";
import { readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

/**
 * Does this session want something from you — the question a row's status dot
 * answers, asked of a task we only have the polled DTO for.
 *
 * Grey is the vocabulary's "nothing owed", so anything else is a dot worth
 * counting: blue is blocked on you, yellow is working, pending, or unread.
 * Running it through `taskDot` rather than re-deriving the rule is the point —
 * the space's dots have to mean what the session rows' dots mean, and there is
 * one function that decides that.
 *
 * The renderer-only inputs (a live session's streaming and permission prompts)
 * are absent here, and can only turn a row yellow or blue that this already
 * counts for another reason, or that is genuinely quiet in the poll. So this
 * can undercount a session that started moving since the last poll, never
 * overcount one.
 */
export function wantsAttention(
  task: Task,
  lastViewedAt: TaskTimestamps,
): boolean {
  const { tone } = taskDot({
    isUnread: isTaskUnread(taskActivityAt(task), lastViewedAt[task.id]),
    taskRunStatus: task.latest_run?.status ?? undefined,
    // A run's mode decides whether its status is a claim about work at all, so
    // without it the "Pending" rows never count. It rides on the run's state,
    // which the poll already carries.
    runMode: readRunMode(task.latest_run?.state),
    workspaceMode:
      task.latest_run?.environment === "cloud" ? "cloud" : undefined,
    prUrl: readPrUrls(task.latest_run?.output)[0] ?? null,
  });
  return tone !== "gray";
}

export type TaskTimestamps = ReturnType<typeof useTaskViewed>["timestamps"];

/**
 * How many sessions in a channel want attention, by channel id — what a space
 * row draws its dots from.
 *
 * Counts what the rows inside would show, off the same two inputs a session
 * row's own dot comes from, so the space's count and the rows under it can't
 * disagree. The mentions feed behind `useIsChannelUnread` answers a different
 * question — someone named you — which is why a bold channel name and these dots
 * are not the same signal.
 *
 * Everyone's sessions, not just yours. A space is shared, its rows come from
 * `getTasksPage({ channel })` with no author filter, and the channel view reads
 * the same list this way — so counting only your own left a teammate's unread
 * session showing a dot on its row and none on the space above it.
 *
 * Built once for the whole list and returned as a lookup, so a sidebar of dozens
 * of spaces is one pass over the task list rather than a pass per row. The
 * answer is a number, which is what lets the memoized space rows compare it and
 * skip re-rendering on a poll that changed nothing.
 */
export function useUnreadSessionCount(): (
  channelId: string | undefined,
) => number {
  const { data: tasks } = useTasks({ showAllUsers: true });
  const { timestamps } = useTaskViewed();
  const archivedTaskIds = useArchivedTaskIds();
  const counts = useMemo(
    () =>
      countSessionsByChannel(
        tasks ?? [],
        // Archived sessions are dropped from every list a space can show, so
        // counting them marks a space with a dot that nothing behind it
        // explains: open the space and the row it stands for isn't there.
        (task) =>
          !archivedTaskIds.has(task.id) && wantsAttention(task, timestamps),
      ),
    [tasks, timestamps, archivedTaskIds],
  );
  return useMemo(
    () => (channelId) => (channelId ? (counts.get(channelId) ?? 0) : 0),
    [counts],
  );
}
