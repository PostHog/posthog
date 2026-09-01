import type { Adapter } from "@posthog/shared";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SessionAdapterState {
  adaptersByRunId: Record<string, Adapter>;
  setAdapter: (taskRunId: string, adapter: Adapter) => void;
  getAdapter: (taskRunId: string) => Adapter | undefined;
  removeAdapter: (taskRunId: string) => void;
}

export const useSessionAdapterStore = create<SessionAdapterState>()(
  persist(
    (set, get) => ({
      adaptersByRunId: {},
      setAdapter: (taskRunId, adapter) =>
        set((state) => ({
          adaptersByRunId: { ...state.adaptersByRunId, [taskRunId]: adapter },
        })),
      getAdapter: (taskRunId) => get().adaptersByRunId[taskRunId],
      removeAdapter: (taskRunId) =>
        set((state) => {
          const { [taskRunId]: _removed, ...rest } = state.adaptersByRunId;
          return { adaptersByRunId: rest };
        }),
    }),
    {
      name: "session-adapter-storage",
      storage: electronStorage,
      partialize: (state) => ({
        adaptersByRunId: state.adaptersByRunId,
      }),
    },
  ),
);
