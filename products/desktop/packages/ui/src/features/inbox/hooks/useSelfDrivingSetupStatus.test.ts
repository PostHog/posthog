import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  sourceConfigs: undefined as { enabled: boolean }[] | undefined,
  sourcesLoading: false,
  scoutConfigs: undefined as { enabled: boolean }[] | undefined,
  scoutsLoading: false,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useSignalSourceConfigs", () => ({
  useSignalSourceConfigs: () => ({
    data: mocks.sourceConfigs,
    isLoading: mocks.sourcesLoading,
  }),
}));

vi.mock("@posthog/ui/features/scouts/hooks/useScoutConfigs", () => ({
  useScoutConfigs: () => ({
    data: mocks.scoutConfigs,
    isLoading: mocks.scoutsLoading,
  }),
}));

import { useSelfDrivingSetupStatus } from "./useSelfDrivingSetupStatus";

describe("useSelfDrivingSetupStatus", () => {
  it.each([
    ["no sources or scouts", [], [], false],
    ["only a disabled source", [{ enabled: false }], [], false],
    ["an enabled source", [{ enabled: true }], [], true],
    ["only an enabled scout", [], [{ enabled: true }], true],
  ] as const)(
    "reports isConfigured=%s for %s",
    (_label, sourceConfigs, scoutConfigs, expected) => {
      mocks.sourceConfigs = [...sourceConfigs];
      mocks.scoutConfigs = [...scoutConfigs];

      const { result } = renderHook(() => useSelfDrivingSetupStatus());

      expect(result.current.isConfigured).toBe(expected);
    },
  );

  it("stays loading until both queries settle", () => {
    mocks.sourceConfigs = undefined;
    mocks.scoutConfigs = undefined;
    mocks.sourcesLoading = true;
    mocks.scoutsLoading = false;

    const { result } = renderHook(() => useSelfDrivingSetupStatus());

    expect(result.current.isLoading).toBe(true);
  });
});
