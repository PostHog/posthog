import type {
  PiModelSelection,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/** Deferred Pi settings selected while a cloud sandbox is inactive. They are applied after its next startup and before the triggering prompt. */
export interface PiPendingConfig {
  model?: PiModelSelection;
  thinkingLevel?: PiThinkingLevel;
}

interface PiPendingConfigState {
  configsByRunKey: Record<string, PiPendingConfig>;
  setConfig: (taskId: string, runId: string, config: PiPendingConfig) => void;
  clearConfig: (taskId: string, runId: string) => void;
}

function runKey(taskId: string, runId: string): string {
  return `${taskId}:${runId}`;
}

export const usePiPendingConfigStore = create<PiPendingConfigState>()(
  persist(
    (set) => ({
      configsByRunKey: {},
      setConfig: (taskId, runId, config) =>
        set((state) => {
          const key = runKey(taskId, runId);
          return {
            configsByRunKey: {
              ...state.configsByRunKey,
              [key]: { ...state.configsByRunKey[key], ...config },
            },
          };
        }),
      clearConfig: (taskId, runId) =>
        set((state) => {
          const { [runKey(taskId, runId)]: _, ...configsByRunKey } =
            state.configsByRunKey;
          return { configsByRunKey };
        }),
    }),
    {
      name: "pi-pending-config-storage",
      storage: electronStorage,
      partialize: (state) => ({ configsByRunKey: state.configsByRunKey }),
    },
  ),
);

export function getPiPendingConfig(
  state: PiPendingConfigState,
  taskId: string,
  runId: string | undefined,
): PiPendingConfig | undefined {
  return runId ? state.configsByRunKey[runKey(taskId, runId)] : undefined;
}
