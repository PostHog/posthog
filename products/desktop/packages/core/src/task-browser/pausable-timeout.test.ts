import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PausableTimeout } from "./pausable-timeout";

describe("PausableTimeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not count the time the run waits for the user", () => {
    const onTimeout = vi.fn();
    const timeout = new PausableTimeout(1_000, onTimeout);

    vi.advanceTimersByTime(600);
    timeout.pause();
    timeout.pause();
    vi.advanceTimersByTime(5_000);
    timeout.unpause();
    vi.advanceTimersByTime(5_000);
    expect(onTimeout).not.toHaveBeenCalled();

    timeout.unpause();
    vi.advanceTimersByTime(399);
    expect(onTimeout).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onTimeout).toHaveBeenCalledOnce();
  });

  it("never fires after it stops", () => {
    const onTimeout = vi.fn();
    const timeout = new PausableTimeout(1_000, onTimeout);

    timeout.stop();
    timeout.unpause();
    vi.advanceTimersByTime(2_000);

    expect(onTimeout).not.toHaveBeenCalled();
  });
});
