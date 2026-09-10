import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDebouncedStorage } from "./panelLayoutStore";

function fakeBase() {
  return {
    getItem: vi.fn(() => null as string | null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  };
}

describe("createDebouncedStorage", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("coalesces rapid writes to the same key into a single write", () => {
    const base = fakeBase();
    const storage = createDebouncedStorage(base, 200);

    storage.setItem("k", "a");
    storage.setItem("k", "b");
    storage.setItem("k", "c");
    expect(base.setItem).not.toHaveBeenCalled();

    vi.advanceTimersByTime(200);
    expect(base.setItem).toHaveBeenCalledTimes(1);
    expect(base.setItem).toHaveBeenCalledWith("k", "c");
  });

  it("passes reads through synchronously", () => {
    const base = fakeBase();
    base.getItem.mockReturnValue("v");
    const storage = createDebouncedStorage(base, 200);

    expect(storage.getItem("k")).toBe("v");
    expect(base.getItem).toHaveBeenCalledWith("k");
  });

  it("cancels a pending write when the key is removed", () => {
    const base = fakeBase();
    const storage = createDebouncedStorage(base, 200);

    storage.setItem("k", "a");
    storage.removeItem("k");
    vi.advanceTimersByTime(200);

    expect(base.setItem).not.toHaveBeenCalled();
    expect(base.removeItem).toHaveBeenCalledWith("k");
  });

  it("debounces different keys independently", () => {
    const base = fakeBase();
    const storage = createDebouncedStorage(base, 200);

    storage.setItem("a", "1");
    storage.setItem("b", "2");
    vi.advanceTimersByTime(200);

    expect(base.setItem).toHaveBeenCalledTimes(2);
  });
});
