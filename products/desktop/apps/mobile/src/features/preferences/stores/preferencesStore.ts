import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type ThemePreference = "light" | "dark" | "system";

export type FontSizePreference = "small" | "default" | "large" | "xlarge";

/**
 * Multiplier applied to every rendered font size. Consumed by the global
 * `Text.render` patch in `lib/textDefaults`, which scales each text node's
 * explicit `fontSize` by this factor. Children without an explicit size keep
 * inheriting their (already-scaled) parent, so the whole UI scales uniformly.
 */
export const FONT_SCALE_BY_PREFERENCE: Record<FontSizePreference, number> = {
  small: 0.9,
  default: 1,
  large: 1.15,
  xlarge: 1.3,
};

/**
 * iOS reads noticeably smaller than Android at the same point size, so iOS
 * ships one notch larger out of the box. Other platforms keep the 1.0
 * baseline. Either way the user can change it in Settings.
 */
const DEFAULT_FONT_SIZE: FontSizePreference =
  Platform.OS === "ios" ? "large" : "default";

export type CompletionSound =
  | "meep"
  | "meep-smol"
  | "knock"
  | "ring"
  | "shoot"
  | "slide"
  | "drop"
  | "icq";

export type InitialTaskMode = "plan" | "last_used";

export type DefaultReasoningEffort =
  | "low"
  | "medium"
  | "high"
  | "xhigh"
  | "max"
  | "last_used";

interface PreferencesState {
  pingsEnabled: boolean;
  setPingsEnabled: (enabled: boolean) => void;
  pushNotificationsEnabled: boolean;
  setPushNotificationsEnabled: (enabled: boolean) => void;

  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;

  fontSize: FontSizePreference;
  setFontSize: (size: FontSizePreference) => void;

  completionSound: CompletionSound;
  setCompletionSound: (sound: CompletionSound) => void;
  completionVolume: number;
  setCompletionVolume: (volume: number) => void;
  scaleSoundWithTaskLength: boolean;
  setScaleSoundWithTaskLength: (enabled: boolean) => void;

  defaultInitialTaskMode: InitialTaskMode;
  setDefaultInitialTaskMode: (mode: InitialTaskMode) => void;
  /** Most recent mode the user picked in the new-task composer. Persisted so
   *  `defaultInitialTaskMode === "last_used"` can pre-fill it next time. */
  lastNewTaskMode: string;
  setLastNewTaskMode: (mode: string) => void;

  defaultReasoningEffort: DefaultReasoningEffort;
  setDefaultReasoningEffort: (effort: DefaultReasoningEffort) => void;
  /** Most recent reasoning effort the user picked. Persisted so
   *  `defaultReasoningEffort === "last_used"` can pre-fill it next time. */
  lastUsedReasoningEffort: string;
  setLastUsedReasoningEffort: (effort: string) => void;

  autoPublishCloudRuns: boolean;
  setAutoPublishCloudRuns: (enabled: boolean) => void;

  rtkEnabledCloud: boolean;
  setRtkEnabledCloud: (enabled: boolean) => void;
}

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      pingsEnabled: true,
      setPingsEnabled: (enabled) => set({ pingsEnabled: enabled }),
      pushNotificationsEnabled: true,
      setPushNotificationsEnabled: (enabled) =>
        set({ pushNotificationsEnabled: enabled }),

      theme: "system",
      setTheme: (theme) => set({ theme }),

      fontSize: DEFAULT_FONT_SIZE,
      setFontSize: (size) => set({ fontSize: size }),

      completionSound: "meep",
      setCompletionSound: (sound) => set({ completionSound: sound }),
      completionVolume: 70,
      setCompletionVolume: (volume) =>
        set({
          completionVolume: Math.max(0, Math.min(100, Math.round(volume))),
        }),
      scaleSoundWithTaskLength: false,
      setScaleSoundWithTaskLength: (enabled) =>
        set({ scaleSoundWithTaskLength: enabled }),

      defaultInitialTaskMode: "plan",
      setDefaultInitialTaskMode: (mode) =>
        set({ defaultInitialTaskMode: mode }),
      lastNewTaskMode: "plan",
      setLastNewTaskMode: (mode) => set({ lastNewTaskMode: mode }),

      defaultReasoningEffort: "last_used",
      setDefaultReasoningEffort: (effort) =>
        set({ defaultReasoningEffort: effort }),
      lastUsedReasoningEffort: "high",
      setLastUsedReasoningEffort: (effort) =>
        set({ lastUsedReasoningEffort: effort }),

      autoPublishCloudRuns: true,
      setAutoPublishCloudRuns: (enabled) =>
        set({ autoPublishCloudRuns: enabled }),

      rtkEnabledCloud: true,
      setRtkEnabledCloud: (enabled) => set({ rtkEnabledCloud: enabled }),
    }),
    {
      name: "posthog-preferences",
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({
        pingsEnabled: state.pingsEnabled,
        pushNotificationsEnabled: state.pushNotificationsEnabled,
        theme: state.theme,
        fontSize: state.fontSize,
        completionSound: state.completionSound,
        completionVolume: state.completionVolume,
        scaleSoundWithTaskLength: state.scaleSoundWithTaskLength,
        defaultInitialTaskMode: state.defaultInitialTaskMode,
        lastNewTaskMode: state.lastNewTaskMode,
        defaultReasoningEffort: state.defaultReasoningEffort,
        lastUsedReasoningEffort: state.lastUsedReasoningEffort,
        autoPublishCloudRuns: state.autoPublishCloudRuns,
        rtkEnabledCloud: state.rtkEnabledCloud,
      }),
    },
  ),
);
