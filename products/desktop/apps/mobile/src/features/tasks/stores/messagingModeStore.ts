import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type MessagingMode = "queue" | "steer";

interface MessagingModeState {
  /** Per-task overrides. Absent entries fall back to `defaultMode`. */
  modesByTaskId: Record<string, MessagingMode>;
  defaultMode: MessagingMode;
  setMode: (taskId: string, mode: MessagingMode) => void;
  setDefaultMode: (mode: MessagingMode) => void;
  getEffectiveMode: (taskId: string | undefined) => MessagingMode;
}

/**
 * Mobile sessions are all cloud, where steer is stable, so the default moved to
 * steer. Existing installs persisted "queue" under v0 and would keep it, so v1
 * rehydrates them to steer. Per-task overrides are untouched; an explicit
 * "queue" default is indistinguishable from the old default, so it is reset too.
 */
export function migrateMessagingModeState(
  persisted: unknown,
  version: number,
): Partial<MessagingModeState> {
  const state = (persisted ?? {}) as Partial<MessagingModeState>;
  return version < 1 ? { ...state, defaultMode: "steer" } : state;
}

export const useMessagingModeStore = create<MessagingModeState>()(
  persist(
    (set, get) => ({
      modesByTaskId: {},
      defaultMode: "steer",
      setMode: (taskId, mode) =>
        set((state) => ({
          modesByTaskId: { ...state.modesByTaskId, [taskId]: mode },
        })),
      setDefaultMode: (defaultMode) => set({ defaultMode }),
      getEffectiveMode: (taskId) => {
        const state = get();
        return (
          (taskId ? state.modesByTaskId[taskId] : undefined) ??
          state.defaultMode
        );
      },
    }),
    {
      name: "messaging-mode-storage",
      storage: createJSONStorage(() => AsyncStorage),
      version: 1,
      migrate: migrateMessagingModeState,
      partialize: (state) => ({
        modesByTaskId: state.modesByTaskId,
        defaultMode: state.defaultMode,
      }),
    },
  ),
);
