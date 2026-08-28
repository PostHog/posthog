import { create } from "zustand";

// A freeform canvas generation we kicked off in this client and want to toast
// about when it finishes. Registered at start (not derived from the dashboard
// record, whose generationTaskId is never cleared), so the watcher only ever
// announces generations the user actually started this session — never a stale
// association on reload.
export interface TrackedCanvasGeneration {
  taskId: string;
  dashboardId: string;
  channelId: string;
  name: string;
}

interface CanvasGenerationTrackerState {
  // Keyed by taskId.
  tracked: Record<string, TrackedCanvasGeneration>;
  track: (entry: TrackedCanvasGeneration) => void;
  // Keep the display name fresh when a freshly-created canvas is auto-renamed
  // from its prompt after generation has already started.
  updateName: (taskId: string, name: string) => void;
  untrack: (taskId: string) => void;
}

export const useCanvasGenerationTrackerStore =
  create<CanvasGenerationTrackerState>((set) => ({
    tracked: {},
    track: (entry) =>
      set((s) => ({ tracked: { ...s.tracked, [entry.taskId]: entry } })),
    updateName: (taskId, name) =>
      set((s) =>
        s.tracked[taskId]
          ? {
              tracked: {
                ...s.tracked,
                [taskId]: { ...s.tracked[taskId], name },
              },
            }
          : s,
      ),
    untrack: (taskId) =>
      set((s) => {
        if (!s.tracked[taskId]) return s;
        const { [taskId]: _removed, ...rest } = s.tracked;
        return { tracked: rest };
      }),
  }));
