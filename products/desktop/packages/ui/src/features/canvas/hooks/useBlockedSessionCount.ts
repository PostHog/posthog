import { countSessionsByChannel } from "@posthog/core/canvas/channelUnread";
import type { Task } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { useAwaitingInputTasks } from "@posthog/ui/features/tasks/useAwaitingInputTasks";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

const NO_BLOCKED: ReadonlySet<string> = new Set();

/**
 * The tasks whose session is waiting on an answer from you — what turns a row
 * blue, and what puts it at the top of its space.
 *
 * Two sources, because neither alone covers the whole life of a prompt. An attached session sees
 * the ask and the answer as they happen, and is the authority for its own task: answer a prompt
 * and the row clears without waiting on a poll. But a session is attached only once something
 * opens it, so on a fresh launch the app would claim every waiting run is quiet, which is why
 * the server's own record of the outstanding request seeds the rest.
 *
 * Sessions are selected as a sorted key rather than the session map: the store's sessions change
 * identity on every streamed event, and this runs in the sidebar's own render, so the projection
 * has to settle to a value that only changes when the blocked set does. The set is then built off
 * that key, which keeps it one object across renders, because the space tree memoizes on its
 * identity.
 */
export function useBlockedTaskIds(): ReadonlySet<string> {
  const attachedKey = useSessionStore((state) =>
    Object.values(state.sessions)
      .map(
        (session) =>
          `${session.taskRunId}:${session.taskId}:${session.pendingPermissions.size > 0 ? "1" : "0"}`,
      )
      .sort()
      .join(","),
  );
  const awaitingTasks = useAwaitingInputTasks();
  const serverKey = useMemo(
    () =>
      awaitingTasks
        .map((task) => `${task.id}:${task.latest_run?.id ?? ""}`)
        .sort()
        .join(","),
    [awaitingTasks],
  );
  return useMemo(() => {
    const pendingByRun = new Map<string, boolean>();
    const blockedIds = new Set<string>();
    for (const entry of splitKey(attachedKey)) {
      const [taskRunId, taskId, pending] = entry.split(":");
      if (!taskRunId || !taskId) continue;
      pendingByRun.set(taskRunId, pending === "1");
      if (pending === "1") blockedIds.add(taskId);
    }
    for (const entry of splitKey(serverKey)) {
      const [taskId, taskRunId] = entry.split(":");
      if (!taskId) continue;
      // Matched on the run, not the task. A session for this exact run has the newer word on the
      // ask, so answering it here clears the row without waiting for the poll. A session for an
      // older run of the same task says nothing about this one, and sessions outlive their runs.
      if (taskRunId && pendingByRun.get(taskRunId) === false) continue;
      blockedIds.add(taskId);
    }
    return blockedIds.size > 0 ? blockedIds : NO_BLOCKED;
  }, [attachedKey, serverKey]);
}

function splitKey(key: string): string[] {
  return key ? key.split(",") : [];
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
  // The waiting tasks carry their own channel, which is what makes the count independent of the
  // list above: that list is one page of the newest tasks, and a run can sit waiting long enough
  // to fall off it, leaving its space with no dot for a session that wants an answer.
  const awaitingTasks = useAwaitingInputTasks();
  const blocked = useBlockedTaskIds();
  const archivedTaskIds = useArchivedTaskIds();
  const counts = useMemo(() => {
    if (blocked.size === 0) return new Map<string, number>();
    const byId = new Map<string, Task>();
    for (const task of [...awaitingTasks, ...(tasks ?? [])]) {
      if (!byId.has(task.id)) byId.set(task.id, task);
    }
    // Archived alongside the yellow count, for the same reason: a space's
    // lists drop them, so a dot for one points at a row you cannot reach.
    return countSessionsByChannel(
      [...byId.values()],
      (task) => blocked.has(task.id) && !archivedTaskIds.has(task.id),
    );
  }, [awaitingTasks, blocked, tasks, archivedTaskIds]);
  return useMemo(
    () => (channelId) => (channelId ? (counts.get(channelId) ?? 0) : 0),
    [counts],
  );
}
