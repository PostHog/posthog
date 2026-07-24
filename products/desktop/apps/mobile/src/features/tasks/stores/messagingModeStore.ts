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

export const useMessagingModeStore = create<MessagingModeState>()(
  persist(
    (set, get) => ({
      modesByTaskId: {},
      defaultMode: "queue",
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
      partialize: (state) => ({
        modesByTaskId: state.modesByTaskId,
        defaultMode: state.defaultMode,
      }),
    },
  ),
);
