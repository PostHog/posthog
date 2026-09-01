import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type MessagingMode = "queue" | "steer";

interface MessagingModeState {
  modesByTaskId: Record<string, MessagingMode>;
  setMode: (taskId: string, mode: MessagingMode) => void;
}

export const useMessagingModeStore = create<MessagingModeState>()(
  persist(
    (set) => ({
      modesByTaskId: {},
      setMode: (taskId, mode) =>
        set((state) => ({
          modesByTaskId: { ...state.modesByTaskId, [taskId]: mode },
        })),
    }),
    {
      name: "messaging-mode-storage",
      storage: electronStorage,
      partialize: (state) => ({ modesByTaskId: state.modesByTaskId }),
    },
  ),
);
