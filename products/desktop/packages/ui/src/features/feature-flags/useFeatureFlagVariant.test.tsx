import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useFeatureFlagVariant } from "./useFeatureFlagVariant";

const { flags } = vi.hoisted(() => ({
  flags: {
    getVariant: vi.fn<(key: string) => string | undefined>(),
    onFlagsLoaded: vi.fn<(handler: () => void) => () => void>(),
  },
}));

vi.mock("@posthog/di/react", () => ({ useService: () => flags }));

describe("useFeatureFlagVariant", () => {
  beforeEach(() => {
    flags.getVariant.mockReset();
    flags.onFlagsLoaded.mockReset();
    flags.onFlagsLoaded.mockReturnValue(() => undefined);
  });

  it("updates when feature flags load", () => {
    let onFlagsLoaded: (() => void) | undefined;
    flags.getVariant
      .mockReturnValueOnce(undefined)
      .mockReturnValueOnce(undefined)
      .mockReturnValue("test");
    flags.onFlagsLoaded.mockImplementation((handler) => {
      onFlagsLoaded = handler;
      return () => undefined;
    });

    const { result } = renderHook(() => useFeatureFlagVariant("report-chat"));
    expect(result.current).toBeUndefined();

    act(() => onFlagsLoaded?.());

    expect(result.current).toBe("test");
    expect(flags.getVariant).toHaveBeenCalledWith("report-chat");
  });
});
