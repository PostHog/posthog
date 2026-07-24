import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sessionService = vi.hoisted(() => ({
  ensureEventsLoaded: vi.fn().mockResolvedValue(undefined),
  scheduleEventEviction: vi.fn(),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => sessionService,
}));

import { useSessionEventsResidency } from "./useSessionEventsResidency";

describe("useSessionEventsResidency", () => {
  beforeEach(() => {
    sessionService.ensureEventsLoaded.mockClear();
    sessionService.scheduleEventEviction.mockClear();
  });

  it("loads events on mount and schedules eviction on unmount", () => {
    const { unmount } = renderHook(() => useSessionEventsResidency("task-1"));

    expect(sessionService.ensureEventsLoaded).toHaveBeenCalledWith("task-1");
    expect(sessionService.scheduleEventEviction).not.toHaveBeenCalled();

    unmount();
    expect(sessionService.scheduleEventEviction).toHaveBeenCalledWith("task-1");
  });

  it("does nothing without a taskId", () => {
    const { unmount } = renderHook(() => useSessionEventsResidency(undefined));
    unmount();

    expect(sessionService.ensureEventsLoaded).not.toHaveBeenCalled();
    expect(sessionService.scheduleEventEviction).not.toHaveBeenCalled();
  });

  it("defers eviction until the last concurrent viewer unmounts", () => {
    const first = renderHook(() => useSessionEventsResidency("task-1"));
    const second = renderHook(() => useSessionEventsResidency("task-1"));

    first.unmount();
    expect(sessionService.scheduleEventEviction).not.toHaveBeenCalled();

    second.unmount();
    expect(sessionService.scheduleEventEviction).toHaveBeenCalledTimes(1);
    expect(sessionService.scheduleEventEviction).toHaveBeenCalledWith("task-1");
  });

  it("schedules eviction for the old task when taskId changes", () => {
    const { rerender, unmount } = renderHook(
      ({ taskId }: { taskId: string }) => useSessionEventsResidency(taskId),
      { initialProps: { taskId: "task-1" } },
    );

    rerender({ taskId: "task-2" });
    expect(sessionService.scheduleEventEviction).toHaveBeenCalledWith("task-1");
    expect(sessionService.ensureEventsLoaded).toHaveBeenLastCalledWith(
      "task-2",
    );

    unmount();
    expect(sessionService.scheduleEventEviction).toHaveBeenCalledWith("task-2");
  });
});
