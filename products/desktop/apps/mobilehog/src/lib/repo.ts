import * as SecureStore from "expo-secure-store";
import { create } from "zustand";

const KEY = "mobilehog_repository";

interface RepoState {
  // undefined = not chosen yet, null = explicitly none.
  repository: string | null | undefined;
  hydrate: () => Promise<void>;
  setRepository: (repository: string | null) => Promise<void>;
}

export const useRepo = create<RepoState>((set) => ({
  repository: undefined,
  hydrate: async () => {
    try {
      const raw = await SecureStore.getItemAsync(KEY);
      set({ repository: raw === null ? undefined : raw === "" ? null : raw });
    } catch {
      set({ repository: undefined });
    }
  },
  setRepository: async (repository) => {
    set({ repository });
    await SecureStore.setItemAsync(KEY, repository ?? "");
  },
}));
