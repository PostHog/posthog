import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  useThreadNavigationStore,
  useThreadScrollRequest,
} from "./threadNavigationStore";

beforeEach(() => {
  useThreadNavigationStore.setState({ scrollRequests: {} });
  // The retry loop runs on animation frames, so the test drives them rather than waiting.
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/** Advance far enough for the loop to settle or exhaust its attempts. */
function runFrames(count: number) {
  act(() => {
    vi.advanceTimersByTime(count * 16);
  });
}

describe("useThreadScrollRequest", () => {
  it("serves a request from another pane and consumes it", () => {
    const jump = vi.fn().mockReturnValue(true);
    renderHook(() => useThreadScrollRequest("task-1", jump));

    act(() => {
      useThreadNavigationStore
        .getState()
        .requestScrollToMessage("task-1", "turn-10-1-user");
    });
    runFrames(10);

    expect(jump).toHaveBeenCalledWith("turn-10-1-user");
    // Cleared, so re-rendering for any other reason can't re-fire the jump and
    // yank the transcript back.
    expect(useThreadNavigationStore.getState().scrollRequests["task-1"]).toBe(
      null,
    );
  });

  it("re-fires when the same message is requested again", () => {
    const jump = vi.fn().mockReturnValue(true);
    renderHook(() => useThreadScrollRequest("task-1", jump));
    const request = () => {
      act(() => {
        useThreadNavigationStore
          .getState()
          .requestScrollToMessage("task-1", "turn-10-1-user");
      });
      runFrames(10);
    };

    request();
    const afterFirst = jump.mock.calls.length;
    jump.mockClear();
    request();

    expect(afterFirst).toBeGreaterThan(0);
    expect(jump).toHaveBeenCalledWith("turn-10-1-user");
  });

  it("keeps the request pending until the transcript can answer it", () => {
    // The row may not be mounted or measured yet, and the transcript's tab can be off screen
    // when the request arrives. Dropping the request on the first miss is what made the jump
    // work only sometimes.
    const jump = vi.fn().mockReturnValue(false);
    renderHook(() => useThreadScrollRequest("task-1", jump));

    act(() => {
      useThreadNavigationStore
        .getState()
        .requestScrollToMessage("task-1", "turn-10-1-user");
    });
    runFrames(5);

    expect(jump.mock.calls.length).toBeGreaterThan(1);
    expect(useThreadNavigationStore.getState().scrollRequests["task-1"]).toBe(
      "turn-10-1-user",
    );

    jump.mockReturnValue(true);
    runFrames(10);

    expect(useThreadNavigationStore.getState().scrollRequests["task-1"]).toBe(
      null,
    );
  });

  it("gives up on a target the transcript never renders", () => {
    // Otherwise a stale id retries for the life of the mount, and every later request queues
    // behind it.
    const jump = vi.fn().mockReturnValue(false);
    renderHook(() => useThreadScrollRequest("task-1", jump));

    act(() => {
      useThreadNavigationStore
        .getState()
        .requestScrollToMessage("task-1", "no-such-row");
    });
    runFrames(120);

    expect(useThreadNavigationStore.getState().scrollRequests["task-1"]).toBe(
      null,
    );
  });
});
