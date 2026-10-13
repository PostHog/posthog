import * as SecureStore from "expo-secure-store";
import { Appearance } from "react-native";
import { create } from "zustand";

const KEY = "mobilehog_prefs";

export type AppearanceMode = "light" | "dark" | "system";

interface Prefs {
  hedgehogMode: boolean;
  appearance: AppearanceMode;
}

interface PrefsState extends Prefs {
  hydrate: () => Promise<void>;
  set: (patch: Partial<Prefs>) => Promise<void>;
}

const defaults: Prefs = { hedgehogMode: true, appearance: "system" };

function applyAppearance(mode: AppearanceMode): void {
  Appearance.setColorScheme(mode === "system" ? "unspecified" : mode);
}

export const usePrefs = create<PrefsState>((set, get) => ({
  ...defaults,
  hydrate: async () => {
    try {
      const raw = await SecureStore.getItemAsync(KEY);
      const prefs = {
        ...defaults,
        ...(JSON.parse(raw ?? "{}") as Partial<Prefs>),
      };
      set(prefs);
      applyAppearance(prefs.appearance);
    } catch {}
  },
  set: async (patch) => {
    set(patch);
    const { hedgehogMode, appearance } = { ...get(), ...patch };
    applyAppearance(appearance);
    await SecureStore.setItemAsync(
      KEY,
      JSON.stringify({ hedgehogMode, appearance }),
    );
  },
}));
