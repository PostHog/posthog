import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  filesBound: true,
  flagEnabled: true,
}));

vi.mock("@posthog/di/react", () => ({
  useServiceOptional: () => (mocks.filesBound ? {} : null),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => mocks.flagEnabled,
}));

import { useSettingsBackupAvailable } from "./useSettingsBackupAvailable";

describe("useSettingsBackupAvailable", () => {
  it.each([
    ["files bound and flag on", true, true, true],
    ["files bound and flag off", true, false, false],
    ["files missing and flag on", false, true, false],
    ["files missing and flag off", false, false, false],
  ])("%s", (_name, filesBound, flagEnabled, expected) => {
    mocks.filesBound = filesBound;
    mocks.flagEnabled = flagEnabled;

    const { result } = renderHook(() => useSettingsBackupAvailable());

    expect(result.current).toBe(expected);
  });
});
