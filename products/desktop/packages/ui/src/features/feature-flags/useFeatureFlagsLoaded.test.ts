import { describe, expect, it, vi } from "vitest";
import type { FeatureFlags } from "./identifiers";
import { resolveFeatureFlagAfterLoad } from "./useFeatureFlagsLoaded";

describe("resolveFeatureFlagAfterLoad", () => {
  it("reads the flag only after the initial payload arrives", async () => {
    let enabled = false;
    let handleLoaded: (() => void) | undefined;
    const unsubscribe = vi.fn();
    const flags: FeatureFlags = {
      isEnabled: vi.fn(() => enabled),
      getPayload: vi.fn(),
      getVariant: vi.fn(),
      onFlagsLoaded: vi.fn((handler) => {
        handleLoaded = handler;
        return unsubscribe;
      }),
    };

    const result = resolveFeatureFlagAfterLoad(flags, "context-layer", false);
    expect(flags.isEnabled).not.toHaveBeenCalled();

    enabled = true;
    handleLoaded?.();

    await expect(result).resolves.toBe(true);
    expect(unsubscribe).toHaveBeenCalledOnce();
  });
});
