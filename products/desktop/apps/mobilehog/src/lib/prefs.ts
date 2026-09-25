import * as SecureStore from "expo-secure-store";
import { create } from "zustand";

const KEY = "mobilehog_prefs";

interface Prefs {
  hedgehogMode: boolean;
}

interface PrefsState extends Prefs {
  hydrate: () => Promise<void>;
  set: (patch: Partial<Prefs>) => Promise<void>;
}

const defaults: Prefs = { hedgehogMode: true };

export const usePrefs = create<PrefsState>((set, get) => ({
  ...defaults,
  hydrate: async () => {
    try {
      const raw = await SecureStore.getItemAsync(KEY);
      if (raw) set({ ...defaults, ...(JSON.parse(raw) as Partial<Prefs>) });
    } catch {}
  },
  set: async (patch) => {
    set(patch);
    const { hedgehogMode } = { ...get(), ...patch };
    await SecureStore.setItemAsync(KEY, JSON.stringify({ hedgehogMode }));
  },
}));
