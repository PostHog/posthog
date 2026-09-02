import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { RepositoryOption } from "../types";

interface RepositoryCacheState {
  /** Last successfully fetched, sorted list of repository options across all
   *  GitHub integrations. Persisted to AsyncStorage so the picker can render
   *  instantly on cold start while a background refetch confirms/updates the
   *  list. Empty array means "no cache yet". */
  options: RepositoryOption[];
  /** Epoch ms of the last successful write. `null` before any cache hit —
   *  useful if we want to surface a "last updated" hint or invalidate stale
   *  caches in the future. */
  updatedAt: number | null;
  setOptions: (options: RepositoryOption[]) => void;
  clear: () => void;
}

export const useRepositoryCacheStore = create<RepositoryCacheState>()(
  persist(
    (set) => ({
      options: [],
      updatedAt: null,
      setOptions: (options) => set({ options, updatedAt: Date.now() }),
      clear: () => set({ options: [], updatedAt: null }),
    }),
    {
      name: "posthog-repository-cache",
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({
        options: state.options,
        updatedAt: state.updatedAt,
      }),
    },
  ),
);
