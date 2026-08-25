import type { ContextUsage } from "@posthog/core/sessions/contextUsage";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAutoCompact, type AutoCompactArgs } from "./useAutoCompact";

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

function usageAt(percentage: number): ContextUsage {
  return { used: percentage, size: 100, percentage, cost: null, breakdown: null };
}

function props(overrides: Partial<AutoCompactArgs> = {}): AutoCompactArgs {
  return {
    sessionKey: "task-a",
    usage: usageAt(80),
    isCompacting: false,
    isRunning: false,
    sendPrompt: vi.fn().mockResolvedValue(true),
    ...overrides,
  };
}

describe("useAutoCompact", () => {
  beforeEach(() => {
    useSettingsStore.setState({ autoCompactPercent: 70 });
  });

  it("fires once per crossing and not again while the session stays above the line", () => {
    const p = props();
    const { rerender } = renderHook((args) => useAutoCompact(args), {
      initialProps: p,
    });
    expect(p.sendPrompt).toHaveBeenCalledTimes(1);
    rerender({ ...p, usage: usageAt(85) });
    expect(p.sendPrompt).toHaveBeenCalledTimes(1);
  });

  it("re-arms for a different session so the old latch does not suppress it", () => {
    const p = props();
    const { rerender } = renderHook((args) => useAutoCompact(args), {
      initialProps: p,
    });
    expect(p.sendPrompt).toHaveBeenCalledTimes(1);
    // The mounted view swaps to another session already above the threshold.
    rerender({ ...p, sessionKey: "task-b" });
    expect(p.sendPrompt).toHaveBeenCalledTimes(2);
  });
});
