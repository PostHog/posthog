import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextRevealLength, useSmoothedText } from "./useSmoothedText";

describe("nextRevealLength", () => {
  it.each<[string, number, number, number, number, number]>([
    // label                                  current target elapsed rate expected
    ["caught up -> target", 10, 10, 16, 120, 10],
    ["past target -> clamps to target", 12, 10, 16, 120, 10],
    ["120 chars/sec over 100ms -> +12", 0, 100, 100, 120, 12],
    ["never overshoots the target", 95, 100, 1000, 120, 100],
    ["always advances at least one when behind", 0, 100, 0, 120, 1],
    ["snaps when lag exceeds the cap", 0, 5000, 16, 120, 5000],
  ])("%s", (_label, current, target, elapsedMs, rate, expected) => {
    expect(nextRevealLength(current, target, elapsedMs, rate)).toBe(expected);
  });
});

describe("useSmoothedText", () => {
  let now: number;
  let rafCallbacks: Array<(t: number) => void>;
  let cancelSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    now = 0;
    rafCallbacks = [];
    cancelSpy = vi.fn();
    vi.stubGlobal(
      "requestAnimationFrame",
      (cb: (t: number) => void): number => {
        rafCallbacks.push(cb);
        return rafCallbacks.length;
      },
    );
    vi.stubGlobal("cancelAnimationFrame", cancelSpy);
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const flushFrame = (deltaMs: number) => {
    now += deltaMs;
    const callbacks = rafCallbacks;
    rafCallbacks = [];
    act(() => {
      for (const cb of callbacks) cb(now);
    });
  };

  it("shows existing text immediately on mount (no replay)", () => {
    const { result } = renderHook(() => useSmoothedText("already here"));
    expect(result.current).toBe("already here");
  });

  it("reveals appended text gradually at a steady rate, then catches up", () => {
    const { result, rerender } = renderHook(
      ({ t }) => useSmoothedText(t, 100),
      { initialProps: { t: "" } },
    );
    rerender({ t: "x".repeat(50) });

    flushFrame(0); // establish the clock; minimal forward progress
    expect(result.current.length).toBe(1);

    flushFrame(100); // 100ms at 100 chars/sec -> ~10 more chars
    expect(result.current.length).toBe(11);
    expect(result.current.length).toBeLessThan(50);

    flushFrame(1000); // plenty of time -> caught up
    expect(result.current).toBe("x".repeat(50));
  });

  it("snaps when the target is replaced with a shorter value", () => {
    const { result, rerender } = renderHook(
      ({ t }) => useSmoothedText(t, 100),
      {
        initialProps: { t: "hello world, a longer streamed message" },
      },
    );
    rerender({ t: "new" });
    expect(result.current).toBe("new");
  });

  it("snaps immediately when reduced motion is preferred", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("reduce"),
    }));
    const { result, rerender } = renderHook(
      ({ t }) => useSmoothedText(t, 100),
      {
        initialProps: { t: "" },
      },
    );
    rerender({ t: "x".repeat(50) });
    expect(result.current).toBe("x".repeat(50));
  });

  it("does not restart the clock when tokens append while the loop runs", () => {
    const { result, rerender } = renderHook(
      ({ t }) => useSmoothedText(t, 100),
      { initialProps: { t: "" } },
    );
    rerender({ t: "x".repeat(20) });

    flushFrame(0); // establish the clock at now=0, reveal the first char
    expect(result.current.length).toBe(1);

    rerender({ t: "x".repeat(60) }); // more tokens arrive mid-reveal

    flushFrame(100); // a single 100ms delta measured from the original clock
    // 100ms at 100 chars/sec adds ~10 chars onto the 1 already shown. A reset
    // clock would measure 0ms elapsed here and advance by just the minimum 1.
    expect(result.current.length).toBe(11);
  });

  it("cancels the pending frame on unmount", () => {
    const { rerender, unmount } = renderHook(
      ({ t }) => useSmoothedText(t, 100),
      { initialProps: { t: "" } },
    );
    rerender({ t: "x".repeat(50) });
    flushFrame(0); // schedules the next frame, leaving one in flight

    unmount();
    expect(cancelSpy).toHaveBeenCalledTimes(1);
  });
});
