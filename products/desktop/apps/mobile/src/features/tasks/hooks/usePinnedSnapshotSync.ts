import { useEffect } from "react";
import {
  SNAPSHOT_DEBOUNCE_MS,
  usePinnedSnapshotStore,
} from "../stores/pinnedSnapshotStore";
import { useTaskSessionStore } from "../stores/taskSessionStore";
import { usePinnedTasks } from "./usePinnedTasks";

/**
 * Keeps the pinned-task snapshot cache in step with the live sessions.
 *
 * Writes are debounced per task: a streaming turn emits events continuously,
 * and only the tail matters, so the snapshot is written once the task has been
 * quiet for `SNAPSHOT_DEBOUNCE_MS` rather than on every frame of output.
 */
export function usePinnedSnapshotSync(): void {
  const { pinnedTaskIds, hasLoaded } = usePinnedTasks();

  // Unpinning drops the task's cache. Gated on the pin list having actually
  // loaded: an empty list from a pending or failed fetch is not a statement
  // that nothing is pinned, and acting on it would wipe every snapshot.
  useEffect(() => {
    if (!hasLoaded) return;
    usePinnedSnapshotStore.getState().retainPinned(pinnedTaskIds);
  }, [hasLoaded, pinnedTaskIds]);

  useEffect(() => {
    if (pinnedTaskIds.length === 0) return;
    const pinned = new Set(pinnedTaskIds);
    const timers = new Map<string, ReturnType<typeof setTimeout>>();
    // The payload is captured when the events arrive, not when the timer
    // fires: leaving the task screen deletes the session, and a snapshot
    // scheduled just before that must still be written.
    const pending = new Map<
      string,
      { taskTitle?: string; events: unknown[] }
    >();

    const flush = (taskId: string) => {
      timers.delete(taskId);
      const payload = pending.get(taskId);
      pending.delete(taskId);
      if (payload) {
        usePinnedSnapshotStore.getState().saveSnapshot(taskId, payload);
      }
    };

    const unsubscribe = useTaskSessionStore.subscribe((state, previous) => {
      for (const session of Object.values(state.sessions)) {
        if (!pinned.has(session.taskId)) continue;
        // Event-array identity is the store's own "new events arrived" signal:
        // it is replaced only when events are appended or a snapshot lands.
        if (previous.sessions[session.taskRunId]?.events === session.events) {
          continue;
        }
        pending.set(session.taskId, {
          taskTitle: session.taskTitle,
          events: session.events,
        });
        const existing = timers.get(session.taskId);
        if (existing) clearTimeout(existing);
        timers.set(
          session.taskId,
          setTimeout(() => flush(session.taskId), SNAPSHOT_DEBOUNCE_MS),
        );
      }
    });

    return () => {
      unsubscribe();
      // Unmounting must not drop a snapshot that was one tick from being
      // written — flush what is queued instead of discarding it.
      for (const timer of timers.values()) clearTimeout(timer);
      for (const taskId of [...pending.keys()]) flush(taskId);
    };
  }, [pinnedTaskIds]);
}
