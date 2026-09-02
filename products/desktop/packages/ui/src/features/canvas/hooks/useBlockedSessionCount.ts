import { countSessionsByChannel } from "@posthog/core/canvas/channelUnread";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

const NO_BLOCKED: ReadonlySet<string> = new Set();

/**
 * The tasks whose session is waiting on an answer from you — what turns a row
 * blue, and what puts it at the top of its space.
 *
 * Blue is the one state a polled task can't report. "Blocked on you" is a
 * permission prompt an agent raised mid-turn, which lives in the session store
 * and nowhere else, so this reads the live sessions rather than the task list
 * the yellow count comes from. A session running somewhere else is therefore
 * never blue here — the app that holds the prompt is the app that can answer it.
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

/**
 * How many sessions in a channel are waiting on an answer from you, by channel
 * id — the blue dot a space row wears beside its yellow one.
 */
export function useBlockedSessionCount(): (
  channelId: string | undefined,
) => number {
  // Everyone's, for the reason `useUnreadSessionCount` gives: the space is
  // shared and its rows carry no author filter.
  const { data: tasks } = useTasks({ showAllUsers: true });
  const blocked = useBlockedTaskIds();
  const archivedTaskIds = useArchivedTaskIds();
  const counts = useMemo(() => {
    if (blocked.size === 0) return new Map<string, number>();
    // Archived alongside the yellow count, for the same reason: a space's
    // lists drop them, so a dot for one points at a row you cannot reach.
    return countSessionsByChannel(
      tasks ?? [],
      (task) => blocked.has(task.id) && !archivedTaskIds.has(task.id),
    );
  }, [blocked, tasks, archivedTaskIds]);
  return useMemo(
    () => (channelId) => (channelId ? (counts.get(channelId) ?? 0) : 0),
    [counts],
  );
}
