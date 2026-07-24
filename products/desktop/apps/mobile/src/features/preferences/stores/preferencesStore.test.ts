import { beforeEach, describe, expect, it } from "vitest";

import {
  FONT_SCALE_BY_PREFERENCE,
  type FontSizePreference,
  usePreferencesStore,
} from "./preferencesStore";

const INITIAL_STATE = usePreferencesStore.getState();

beforeEach(() => {
  // Reset to the store's defined defaults between tests so persisted state from
  // earlier cases doesn't leak in.
  usePreferencesStore.setState(INITIAL_STATE, true);
});

describe("preferencesStore reasoning effort", () => {
  it("defaults defaultReasoningEffort to last_used", () => {
    expect(usePreferencesStore.getState().defaultReasoningEffort).toBe(
      "last_used",
    );
  });

  it("defaults lastUsedReasoningEffort to high", () => {
    expect(usePreferencesStore.getState().lastUsedReasoningEffort).toBe("high");
  });

  it.each(["low", "medium", "high", "xhigh", "max", "last_used"] as const)(
    "updates defaultReasoningEffort to %s via setter",
    (effort) => {
      usePreferencesStore.getState().setDefaultReasoningEffort(effort);
      expect(usePreferencesStore.getState().defaultReasoningEffort).toBe(
        effort,
      );
    },
  );

  it.each(["low", "medium", "high", "xhigh", "max"] as const)(
    "updates lastUsedReasoningEffort to %s via setter",
    (effort) => {
      usePreferencesStore.getState().setLastUsedReasoningEffort(effort);
      expect(usePreferencesStore.getState().lastUsedReasoningEffort).toBe(
        effort,
      );
    },
  );

  it("keeps lastUsedReasoningEffort independent of defaultReasoningEffort", () => {
    usePreferencesStore.getState().setDefaultReasoningEffort("low");
    usePreferencesStore.getState().setLastUsedReasoningEffort("max");

    const state = usePreferencesStore.getState();
    expect(state.defaultReasoningEffort).toBe("low");
    expect(state.lastUsedReasoningEffort).toBe("max");
  });
});

describe("preferencesStore scale sound with task length", () => {
  it("defaults to false", () => {
    expect(usePreferencesStore.getState().scaleSoundWithTaskLength).toBe(false);
  });

  it.each([true, false])("updates to %s via setter", (enabled) => {
    usePreferencesStore.getState().setScaleSoundWithTaskLength(enabled);
    expect(usePreferencesStore.getState().scaleSoundWithTaskLength).toBe(
      enabled,
    );
  });

  it("persists the value to storage", async () => {
    const AsyncStorage = (
      await import("@react-native-async-storage/async-storage")
    ).default;
    usePreferencesStore.getState().setScaleSoundWithTaskLength(true);
    await Promise.resolve();
    const persisted = await AsyncStorage.getItem("posthog-preferences");
    expect(persisted).not.toBeNull();
    expect(JSON.parse(persisted as string).state.scaleSoundWithTaskLength).toBe(
      true,
    );
  });
});

describe("preferencesStore font size", () => {
  it("defaults to a known preference with a 'default' scale of 1", () => {
    const { fontSize } = usePreferencesStore.getState();
    expect(FONT_SCALE_BY_PREFERENCE[fontSize]).toBeGreaterThanOrEqual(1);
    expect(FONT_SCALE_BY_PREFERENCE.default).toBe(1);
  });

  it.each([
    ["small", 0.9],
    ["large", 1.15],
    ["xlarge", 1.3],
  ] as const)("FONT_SCALE_BY_PREFERENCE.%s equals %s", (size, expected) => {
    expect(FONT_SCALE_BY_PREFERENCE[size]).toBe(expected);
  });

  it.each(["small", "default", "large", "xlarge"] as const)(
    "updates fontSize to %s via setter",
    (size: FontSizePreference) => {
      usePreferencesStore.getState().setFontSize(size);
      expect(usePreferencesStore.getState().fontSize).toBe(size);
    },
  );
});
