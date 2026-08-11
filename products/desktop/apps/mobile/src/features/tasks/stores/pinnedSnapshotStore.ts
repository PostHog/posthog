import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { SessionEvent } from "../types";

/**
 * Cached tails of pinned tasks' sessions, so reopening a pinned task paints
 * its last messages instantly instead of a spinner while the SSE snapshot
 * loads. Purely a display cache: the live session replaces it wholesale on its
 * first payload, and losing it costs nothing but the spinner it was avoiding.
 */

/** Events kept per task. Enough to fill a phone screen, small enough to write often. */
export const MAX_SNAPSHOT_EVENTS = 30;

/** Tasks kept at once; the oldest-saved snapshots are evicted past this. */
export const MAX_SNAPSHOT_TASKS = 20;

/** Quiet period after a session's last event before its snapshot is written. */
export const SNAPSHOT_DEBOUNCE_MS = 2_000;

/**
 * Byte budget per task snapshot. AsyncStorage on Android is one shared SQLite
 * database with a ~6MB default ceiling that also backs auth and preferences —
 * an unbounded snapshot (inline base64 images especially) could push it over
 * and break unrelated stores' writes.
 */
export const MAX_SNAPSHOT_BYTES = 256_000;

export interface PinnedSnapshot {
  /** Epoch ms of the write; also the eviction order. */
  savedAt: number;
  taskTitle?: string;
  /** The tail of the session's events, oldest first. */
  events: SessionEvent[];
}

/**
 * Session events are plain SSE payloads, but a live session can also carry
 * locally-attached values (image blobs, Sets used for echo dedup). Anything
 * that will not survive the JSON round-trip AsyncStorage puts it through is
 * dropped now rather than resurfacing as a corrupt event on the next launch.
 */
function toSerializable(event: SessionEvent): SessionEvent | undefined {
  try {
    const serialized = JSON.stringify(event, (_key, value) =>
      // Inline base64 previews can be megabytes each; the cached tail only
      // needs to paint a placeholder until the live session replaces it.
      typeof value === "string" && value.startsWith("data:")
        ? "data:dropped-from-snapshot"
        : value,
    );
    return serialized === undefined ? undefined : JSON.parse(serialized);
  } catch {
    return undefined;
  }
}

function serializedSize(event: SessionEvent): number {
  try {
    return JSON.stringify(event)?.length ?? 0;
  } catch {
    return 0;
  }
}

/**
 * The newest `MAX_SNAPSHOT_EVENTS` events that can be persisted, oldest first.
 * Events are stored as their round-tripped form so what a freshly written
 * snapshot renders is exactly what it renders after a relaunch.
 */
export function trimSnapshotEvents(
  events: readonly SessionEvent[],
): SessionEvent[] {
  const serializable: SessionEvent[] = [];
  let budget = MAX_SNAPSHOT_BYTES;
  // Walk newest-first so the byte budget keeps the most recent events.
  for (const event of [...events.slice(-MAX_SNAPSHOT_EVENTS)].reverse()) {
    const value = toSerializable(event);
    if (value === undefined) continue;
    const size = serializedSize(value);
    if (size > budget) break;
    budget -= size;
    serializable.unshift(value);
  }
  return serializable;
}

/** Cap the store at `MAX_SNAPSHOT_TASKS`, dropping the oldest-saved snapshots. */
export function evictOldestSnapshots(
  snapshots: Record<string, PinnedSnapshot>,
): Record<string, PinnedSnapshot> {
  const ids = Object.keys(snapshots);
  if (ids.length <= MAX_SNAPSHOT_TASKS) return snapshots;
  const kept = ids
    .sort((a, b) => snapshots[b].savedAt - snapshots[a].savedAt)
    .slice(0, MAX_SNAPSHOT_TASKS);
  const trimmed: Record<string, PinnedSnapshot> = {};
  for (const id of kept) trimmed[id] = snapshots[id];
  return trimmed;
}

/**
 * Keep only the snapshots whose task is still pinned. Unpinning is the user
 * saying they are done with the task, so its cache goes with it.
 */
export function retainPinnedSnapshots(
  snapshots: Record<string, PinnedSnapshot>,
  pinnedTaskIds: readonly string[],
): Record<string, PinnedSnapshot> {
  const pinned = new Set(pinnedTaskIds);
  const ids = Object.keys(snapshots);
  if (ids.every((id) => pinned.has(id))) return snapshots;
  const kept: Record<string, PinnedSnapshot> = {};
  for (const id of ids) {
    if (pinned.has(id)) kept[id] = snapshots[id];
  }
  return kept;
}

interface PinnedSnapshotState {
  snapshots: Record<string, PinnedSnapshot>;
  /** Write (or overwrite) one task's snapshot, trimming and evicting as needed. */
  saveSnapshot: (
    taskId: string,
    snapshot: { taskTitle?: string; events: readonly SessionEvent[] },
  ) => void;
  dropSnapshot: (taskId: string) => void;
  /** Drop every snapshot whose task is no longer pinned. */
  retainPinned: (pinnedTaskIds: readonly string[]) => void;
}

export const usePinnedSnapshotStore = create<PinnedSnapshotState>()(
  persist(
    (set) => ({
      snapshots: {},

      saveSnapshot: (taskId, { taskTitle, events }) =>
        set((state) => {
          const trimmed = trimSnapshotEvents(events);
          // An empty tail would replace a good snapshot with a useless one and
          // then be shown on the next open as a blank thread.
          if (trimmed.length === 0) return state;
          return {
            snapshots: evictOldestSnapshots({
              ...state.snapshots,
              [taskId]: { savedAt: Date.now(), taskTitle, events: trimmed },
            }),
          };
        }),

      dropSnapshot: (taskId) =>
        set((state) => {
          if (!(taskId in state.snapshots)) return state;
          const { [taskId]: _dropped, ...rest } = state.snapshots;
          return { snapshots: rest };
        }),

      retainPinned: (pinnedTaskIds) =>
        set((state) => {
          const kept = retainPinnedSnapshots(state.snapshots, pinnedTaskIds);
          return kept === state.snapshots ? state : { snapshots: kept };
        }),
    }),
    {
      name: "pinned-task-snapshots",
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({ snapshots: state.snapshots }),
    },
  ),
);
