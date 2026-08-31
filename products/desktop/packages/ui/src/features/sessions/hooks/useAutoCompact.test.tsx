import type { ContextUsage } from "@posthog/core/sessions/contextUsage";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { type AutoCompactArgs, useAutoCompact } from "./useAutoCompact";

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

function usageAt(percentage: number): ContextUsage {
  return {
    used: percentage,
    size: 100,
    percentage,
    cost: null,
    breakdown: null,
  };
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

  it("does not start a second compaction after a send while still above the line", async () => {
    let resolveSend: ((sent: boolean) => void) | undefined;
    const sendPrompt = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          resolveSend = resolve;
        }),
    );
    const p = props({ sendPrompt });
    const { rerender } = renderHook((args) => useAutoCompact(args), {
      initialProps: p,
    });
    expect(sendPrompt).toHaveBeenCalledTimes(1);

    // A render arrives while the compaction send is still in flight.
    rerender({ ...p, usage: usageAt(82) });
    expect(sendPrompt).toHaveBeenCalledTimes(1);

    // The send resolves and the session settles still above the threshold; the
    // latch must stay closed rather than firing a second, paid compaction.
    await act(async () => {
      resolveSend?.(true);
    });
    rerender({ ...p, usage: usageAt(83) });
    expect(sendPrompt).toHaveBeenCalledTimes(1);
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
