import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCanvasNavigation } from "./useCanvasNavigation";

vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTaskInput: vi.fn() }));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToChannelDashboard: vi.fn(),
  navigateToChannelTask: vi.fn(),
  navigateToSettings: vi.fn(),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useCreateAndOpenDashboard: () => vi.fn(),
}));

describe("useCanvasNavigation", () => {
  it("prefills a cloud repository within the existing space, then clears it for an empty form", () => {
    const { result } = renderHook(() => useCanvasNavigation("canvas-space"));
    result.current({
      target: "compose-task",
      prompt: "Inspect this PR",
      repository: "example/app",
    });
    expect(openTaskInput).toHaveBeenLastCalledWith({
      channelId: "canvas-space",
      initialPrompt: "Inspect this PR",
      initialCloudRepository: "example/app",
      newTab: true,
    });
    result.current({ target: "new-task" });
    expect(openTaskInput).toHaveBeenLastCalledWith({
      channelId: "canvas-space",
    });
  });
});
