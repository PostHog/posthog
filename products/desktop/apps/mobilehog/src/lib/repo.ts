import * as SecureStore from "expo-secure-store";
import { create } from "zustand";
import { accountStorageKey, sessionIdentity, useAuth } from "@/lib/auth";

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
    if (!useAuth.getState().session) return;
    const identity = sessionIdentity();
    try {
      const raw = await SecureStore.getItemAsync(accountStorageKey(KEY));
      if (sessionIdentity() !== identity) return;
      set({ repository: raw === null ? undefined : raw === "" ? null : raw });
    } catch {
      if (sessionIdentity() === identity) set({ repository: undefined });
    }
  },
  setRepository: async (repository) => {
    set({ repository });
    await SecureStore.setItemAsync(accountStorageKey(KEY), repository ?? "");
  },
}));
