import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SessionConfigState {
  /** Map of taskRunId -> persisted config options */
  configsByRunId: Record<string, SessionConfigOption[]>;
}

interface SessionConfigActions {
  /** Save config options for a task run */
  setConfigOptions: (taskRunId: string, options: SessionConfigOption[]) => void;
  /** Get config options for a task run */
  getConfigOptions: (taskRunId: string) => SessionConfigOption[] | undefined;
  /** Remove config options for a task run */
  removeConfigOptions: (taskRunId: string) => void;
}

type SessionConfigStore = SessionConfigState & SessionConfigActions;

export const useSessionConfigStore = create<SessionConfigStore>()(
  persist(
    (set, get) => ({
      configsByRunId: {},

      setConfigOptions: (taskRunId, options) =>
        set((state) => ({
          configsByRunId: { ...state.configsByRunId, [taskRunId]: options },
        })),

      getConfigOptions: (taskRunId) => get().configsByRunId[taskRunId],

      removeConfigOptions: (taskRunId) =>
        set((state) => {
          const { [taskRunId]: _removed, ...rest } = state.configsByRunId;
          return { configsByRunId: rest };
        }),
    }),
    {
      name: "session-config-storage",
      storage: electronStorage,
      partialize: (state) => ({ configsByRunId: state.configsByRunId }),
    },
  ),
);

/** Non-hook accessor for getting persisted config options */
export function getPersistedConfigOptions(
  taskRunId: string,
): SessionConfigOption[] | undefined {
  return useSessionConfigStore.getState().getConfigOptions(taskRunId);
}

/** Non-hook accessor for setting persisted config options */
export function setPersistedConfigOptions(
  taskRunId: string,
  options: SessionConfigOption[],
): void {
  useSessionConfigStore.getState().setConfigOptions(taskRunId, options);
}

/** Non-hook accessor for removing persisted config options */
export function removePersistedConfigOptions(taskRunId: string): void {
  useSessionConfigStore.getState().removeConfigOptions(taskRunId);
}
