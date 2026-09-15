import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useFileTaskToChannel } from "./useFileTaskToChannel";

const hoisted = vi.hoisted(() => ({
  fileTask: vi.fn(),
  track: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [{ id: "c1", name: "support" }],
    isLoading: false,
  }),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTaskMutations: () => ({ fileTask: hoisted.fileTask }),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({ toast: hoisted.toast }));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: hoisted.track }));

describe("useFileTaskToChannel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.fileTask.mockResolvedValue(undefined);
  });

  // The row menu is the surface a Spaces user files from, so a `file_task`
  // breakdown that misses it reads as if the menu is unused.
  it.each([
    { outcome: "succeeded", fails: false, success: true },
    { outcome: "failed", fails: true, success: false },
  ])("reports a filing that $outcome", async ({ fails, success }) => {
    if (fails) hoisted.fileTask.mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useFileTaskToChannel());

    await act(() => result.current("c1", "t1", "Fix the login"));

    expect(hoisted.track).toHaveBeenCalledTimes(1);
    expect(hoisted.track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.CHANNEL_ACTION,
      {
        action_type: "file_task",
        surface: "task_context_menu",
        channel_id: "c1",
        task_id: "t1",
        success,
      },
    );
  });
});
