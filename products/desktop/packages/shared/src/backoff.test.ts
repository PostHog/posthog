import { afterEach, describe, expect, it, vi } from "vitest";
import { getBackoffDelay, sleepWithBackoff } from "./backoff";

describe("getBackoffDelay", () => {
  it("returns the initial delay for the first attempt", () => {
    expect(getBackoffDelay(0, { initialDelayMs: 100 })).toBe(100);
  });

  it("doubles by default on each subsequent attempt", () => {
    expect(getBackoffDelay(1, { initialDelayMs: 100 })).toBe(200);
    expect(getBackoffDelay(2, { initialDelayMs: 100 })).toBe(400);
    expect(getBackoffDelay(3, { initialDelayMs: 100 })).toBe(800);
  });

  it("honours a custom multiplier", () => {
    expect(getBackoffDelay(2, { initialDelayMs: 100, multiplier: 3 })).toBe(
      900,
    );
  });

  it("caps the delay at maxDelayMs", () => {
    expect(getBackoffDelay(10, { initialDelayMs: 100, maxDelayMs: 1000 })).toBe(
      1000,
    );
  });

  it("does not cap when maxDelayMs is unset", () => {
    expect(getBackoffDelay(4, { initialDelayMs: 100 })).toBe(1600);
  });
});

describe("sleepWithBackoff", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves after the computed backoff delay", async () => {
    vi.useFakeTimers();
    const onResolve = vi.fn();

    const promise = sleepWithBackoff(2, {
      initialDelayMs: 100,
      maxDelayMs: 1000,
    }).then(onResolve);

    await vi.advanceTimersByTimeAsync(399);
    expect(onResolve).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    await promise;
    expect(onResolve).toHaveBeenCalled();
  });
});
