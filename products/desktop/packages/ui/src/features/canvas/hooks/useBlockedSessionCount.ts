import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

const NO_BLOCKED: ReadonlySet<string> = new Set();

/**
 * The tasks whose live session is holding a prompt — what a mounted session
 * knows about itself.
 *
 * A permission prompt an agent raised mid-turn lives in the session store and
 * nowhere else, so this reads the live sessions rather than the polled task
 * list. A session running in another app is therefore absent here: the app that
 * holds the prompt is the app that can answer it.
 *
 * Selected as a sorted key rather than the session map: the store's sessions
 * change identity on every streamed event, and this runs in the sidebar's own
 * render, so the projection has to settle to a value that only changes when the
 * set of blocked tasks does. The set is then built off that key, which keeps it
 * one object across renders — the space tree memoizes on its identity.
 */
export function useBlockedTaskIds(): ReadonlySet<string> {
  const blockedKey = useSessionStore((state) =>
    Object.values(state.sessions)
      .filter((session) => session.pendingPermissions.size > 0)
      .map((session) => session.taskId)
      .sort()
      .join(","),
  );
  return useMemo(
    () => (blockedKey ? new Set(blockedKey.split(",")) : NO_BLOCKED),
    [blockedKey],
  );
}

/** The tasks with a session in this app, whether or not it holds a prompt. */
function useMountedTaskIds(): ReadonlySet<string> {
  const mountedKey = useSessionStore((state) =>
    Object.keys(state.taskIdIndex).sort().join(","),
  );
  return useMemo(
    () => (mountedKey ? new Set(mountedKey.split(",")) : NO_BLOCKED),
    [mountedKey],
  );
}

/**
 * The feed rows for tasks that are waiting, minus the ones a live session can
 * speak for.
 *
 * Rows rather than ids, because a row also carries the space the task is filed
 * in. That is what lets a space count its cold sessions without going through
 * the task list, which it may not have loaded yet.
 */
export function coldAwaitingInputRows(
  items: readonly TaskActivityItem[],
  mounted: ReadonlySet<string>,
): TaskActivityItem[] {
  return items.filter(
    (item) =>
      item.activityKind === "awaiting_input" && !mounted.has(item.taskId),
  );
}

/**
 * Every task waiting on an answer from you, including the ones whose session is
 * cold.
 *
 * A session that isn't mounted holds its prompt in the run log, which costs a
 * fetch and a hydration to read — so before this, a space went blue only once
 * you opened the session that was already waiting. The backend records the same
 * fact when a run stops for input (`push_dispatcher.notify_task_run_awaiting_input`)
 * as one activity row per task, newest wins, which the feed behind the bell
 * already holds. No new request, and it survives a restart.
 *
 * A mounted session outranks its row. The session is live and clears the moment
 * you answer, while the activity row only moves when the next activity lands, so
 * trusting the row over a session that is present would keep a row blue after
 * its prompt was answered.
 *
 * Local runs are the gap. Their prompt is announced client-side and never
 * reaches the backend, so a local session that isn't mounted stays invisible
 * here. Cloud runs, which is most of them, are covered.
 */
export function useAwaitingInputTaskIds(): ReadonlySet<string> {
  const blocked = useBlockedTaskIds();
  const mounted = useMountedTaskIds();
  const { items } = useTaskActivity();
  const coldKey = useMemo(
    () =>
      coldAwaitingInputRows(items, mounted)
        .map((row) => row.taskId)
        .sort()
        .join(","),
    [items, mounted],
  );
  return useMemo(() => {
    if (!coldKey) return blocked;
    const awaiting = new Set(blocked);
    for (const taskId of coldKey.split(",")) awaiting.add(taskId);
    return awaiting;
  }, [blocked, coldKey]);
}

/**
 * How many sessions in a channel are waiting on an answer from you, by channel
 * id — the blue dot a space row wears beside its yellow one.
 *
 * Two passes over two sources, because they place a task differently. A live
 * session gives an id and nothing else, so the task list says which space it is
 * in. A cold one comes from the feed, whose row already carries the space, and
 * reading it from there is what lets a space go blue before the task list has
 * loaded — the row under it does not wait for that list either.
 *
 * Counted as a set of task ids per space, so a task that both sources know about
 * is one session, not two.
 */
export function useBlockedSessionCount(): (
  channelId: string | undefined,
) => number {
  // Everyone's, for the reason `useUnreadSessionCount` gives: the space is
  // shared and its rows carry no author filter.
  const { data: tasks } = useTasks({ showAllUsers: true });
  const blocked = useBlockedTaskIds();
  const mounted = useMountedTaskIds();
  const { items } = useTaskActivity();
  const archivedTaskIds = useArchivedTaskIds();
  const counts = useMemo(() => {
    const bySpace = new Map<string, Set<string>>();
    // Archived alongside the yellow count, for the same reason: a space's
    // lists drop them, so a dot for one points at a row you cannot reach.
    const add = (spaceId: string | null, taskId: string) => {
      if (!spaceId || archivedTaskIds.has(taskId)) return;
      const inSpace = bySpace.get(spaceId) ?? new Set<string>();
      inSpace.add(taskId);
      bySpace.set(spaceId, inSpace);
    };
    for (const task of tasks ?? []) {
      if (blocked.has(task.id)) add(task.channel ?? null, task.id);
    }
    for (const row of coldAwaitingInputRows(items, mounted)) {
      add(row.channelId, row.taskId);
    }
    return bySpace;
  }, [blocked, mounted, items, tasks, archivedTaskIds]);
  return useMemo(
    () => (channelId) => (channelId ? (counts.get(channelId)?.size ?? 0) : 0),
    [counts],
  );
}
