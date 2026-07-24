import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

// Persisted (unlike the transient in-memory echo store, whose entries vanish
// the instant the live SSE copy lands) so a prompt survives the app being
// killed mid-create and can be recovered on the next launch.
const MAX_RECOVERABLE_PROMPTS = 20;

export interface RecoverablePrompt {
  promptText: string;
  createdAt: number;
}

interface PendingPromptRecoveryState {
  byKey: Record<string, RecoverablePrompt>;
  hasHydrated: boolean;
  set: (key: string, promptText: string) => void;
  clear: (key: string) => void;
  setHasHydrated: (hydrated: boolean) => void;
}

function capToNewest(
  byKey: Record<string, RecoverablePrompt>,
): Record<string, RecoverablePrompt> {
  const keys = Object.keys(byKey);
  if (keys.length <= MAX_RECOVERABLE_PROMPTS) return byKey;
  const kept = keys
    .sort((a, b) => byKey[b].createdAt - byKey[a].createdAt)
    .slice(0, MAX_RECOVERABLE_PROMPTS);
  const trimmed: Record<string, RecoverablePrompt> = {};
  for (const key of kept) trimmed[key] = byKey[key];
  return trimmed;
}

export const usePendingPromptRecoveryStore =
  create<PendingPromptRecoveryState>()(
    persist(
      (set) => ({
        byKey: {},
        hasHydrated: false,
        set: (key, promptText) =>
          set((state) => ({
            byKey: capToNewest({
              ...state.byKey,
              [key]: { promptText, createdAt: Date.now() },
            }),
          })),
        clear: (key) =>
          set((state) => {
            if (!(key in state.byKey)) return state;
            const { [key]: _removed, ...rest } = state.byKey;
            return { byKey: rest };
          }),
        setHasHydrated: (hydrated) => set({ hasHydrated: hydrated }),
      }),
      {
        name: "pending-task-prompt-recovery",
        storage: createJSONStorage(() => AsyncStorage),
        partialize: (state) => ({ byKey: state.byKey }),
        onRehydrateStorage: () => (state) => {
          (state ?? usePendingPromptRecoveryStore.getState()).setHasHydrated(
            true,
          );
        },
      },
    ),
  );

export const pendingPromptRecoveryStoreApi = {
  set(key: string, promptText: string): void {
    usePendingPromptRecoveryStore.getState().set(key, promptText);
  },
  clear(key: string): void {
    usePendingPromptRecoveryStore.getState().clear(key);
  },
  getAllNewestFirst(): { key: string; prompt: RecoverablePrompt }[] {
    return Object.entries(usePendingPromptRecoveryStore.getState().byKey)
      .map(([key, prompt]) => ({ key, prompt }))
      .sort((a, b) => b.prompt.createdAt - a.prompt.createdAt);
  },
  whenHydrated(): Promise<void> {
    if (usePendingPromptRecoveryStore.getState().hasHydrated) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      const unsubscribe = usePendingPromptRecoveryStore.subscribe((state) => {
        if (state.hasHydrated) {
          unsubscribe();
          resolve();
        }
      });
    });
  },
};
