import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  useThreadNavigationStore,
  useThreadScrollRequest,
} from "./threadNavigationStore";

beforeEach(() => {
  useThreadNavigationStore.setState({ scrollRequests: {} });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useThreadScrollRequest", () => {
  it("serves a request from another pane and consumes it", () => {
    const jump = vi.fn();
    renderHook(() => useThreadScrollRequest("task-1", jump));

    act(() => {
      useThreadNavigationStore
        .getState()
        .requestScrollToMessage("task-1", "turn-10-1-user");
    });

    expect(jump).toHaveBeenCalledWith("turn-10-1-user");
    // Cleared, so re-rendering for any other reason can't re-fire the jump and
    // yank the transcript back.
    expect(useThreadNavigationStore.getState().scrollRequests["task-1"]).toBe(
      null,
    );
  });

  it("re-fires when the same message is requested again", () => {
    const jump = vi.fn();
    renderHook(() => useThreadScrollRequest("task-1", jump));
    const request = () =>
      act(() => {
        useThreadNavigationStore
          .getState()
          .requestScrollToMessage("task-1", "turn-10-1-user");
      });

    request();
    request();

    expect(jump).toHaveBeenCalledTimes(2);
  });

  it("retries prepared jumps while older rows settle", () => {
    vi.useFakeTimers();
    const prepareForJump = vi.fn();
    const jump = vi.fn();
    renderHook(() =>
      useThreadScrollRequest("task-1", jump, {
        settleFrames: 2,
        prepareForJump,
      }),
    );

    act(() => {
      useThreadNavigationStore
        .getState()
        .requestScrollToMessage("task-1", "turn-1-1-user");
    });
    expect(jump).toHaveBeenCalledTimes(1);

    act(() => vi.runAllTimers());

    expect(jump).toHaveBeenCalledTimes(3);
    expect(prepareForJump).toHaveBeenCalledTimes(3);
    expect(prepareForJump.mock.invocationCallOrder[0]).toBeLessThan(
      jump.mock.invocationCallOrder[0],
    );
  });
});
