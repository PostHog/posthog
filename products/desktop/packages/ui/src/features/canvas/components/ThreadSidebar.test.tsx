import type { Task } from "@posthog/shared/domain-types";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { track } = vi.hoisted(() => ({ track: vi.fn() }));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/canvas/components/ActivityPanel", () => ({
  ActivityPanel: ({ collapsed }: { collapsed?: boolean }) => (
    <div>{collapsed ? "collapsed activity" : "expanded activity"}</div>
  ),
}));
vi.mock("@posthog/ui/features/canvas/components/ThreadPanel", () => ({
  ThreadPanel: () => <div>thread panel</div>,
}));
vi.mock("@posthog/ui/primitives/ResizableSidebar", () => ({
  ResizableSidebar: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track }));

import { ThreadSidebar } from "./ThreadSidebar";

const task = { id: "task-1" } as Task;

describe("ThreadSidebar", () => {
  beforeEach(() => {
    track.mockClear();
    useThreadPanelStore.setState({ collapsed: false });
  });

  it("toggles the activity panel with the keyboard shortcut", () => {
    render(
      <ThreadSidebar taskId={task.id} channelId="channel-1" task={task} />,
    );

    expect(screen.getByText("expanded activity")).toBeTruthy();

    fireEvent.keyDown(document, {
      key: "b",
      metaKey: true,
      altKey: true,
    });

    expect(screen.getByText("collapsed activity")).toBeTruthy();

    fireEvent.keyDown(document, {
      key: "b",
      metaKey: true,
      altKey: true,
    });

    expect(screen.getByText("expanded activity")).toBeTruthy();
    expect(track).toHaveBeenNthCalledWith(1, "Channel action", {
      action_type: "collapse_thread",
      surface: "activity_panel",
      task_id: task.id,
    });
    expect(track).toHaveBeenNthCalledWith(2, "Channel action", {
      action_type: "expand_thread",
      surface: "activity_panel",
      task_id: task.id,
    });
  });
});
