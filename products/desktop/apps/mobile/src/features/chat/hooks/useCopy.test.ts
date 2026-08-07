import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";

const setStringAsync = vi.fn(async (_text: string) => true);
vi.mock("expo-clipboard", () => ({
  setStringAsync: (text: string) => setStringAsync(text),
}));

import { useCopy } from "./useCopy";

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

function renderUseCopy(resetMs?: number) {
  const state: { current: ReturnType<typeof useCopy> } = {
    current: { copied: false, copy: () => {} },
  };
  function Harness() {
    state.current = useCopy(resetMs);
    return null;
  }
  act(() => {
    create(createElement(Harness));
  });
  return state;
}

describe("useCopy", () => {
  it("writes to the clipboard and flips copied true then false", async () => {
    vi.useFakeTimers();
    const state = renderUseCopy(2000);

    expect(state.current.copied).toBe(false);

    await act(async () => {
      state.current.copy("hello");
    });

    expect(setStringAsync).toHaveBeenCalledWith("hello");
    expect(state.current.copied).toBe(true);

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(state.current.copied).toBe(false);
  });

  it("runs onSuccess only after a successful write", async () => {
    setStringAsync.mockRejectedValueOnce(new Error("denied"));
    const onSuccess = vi.fn();
    const state = renderUseCopy();

    await act(async () => {
      state.current.copy("nope", onSuccess);
    });

    expect(state.current.copied).toBe(false);
    expect(onSuccess).not.toHaveBeenCalled();

    await act(async () => {
      state.current.copy("yep", onSuccess);
    });

    expect(state.current.copied).toBe(true);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });
});
