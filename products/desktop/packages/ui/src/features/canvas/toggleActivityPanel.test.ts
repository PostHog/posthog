import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { track } = vi.hoisted(() => ({ track: vi.fn() }));
vi.mock("@posthog/ui/shell/analytics", () => ({ track }));

import { toggleActivityPanel } from "./toggleActivityPanel";

describe("toggleActivityPanel", () => {
  beforeEach(() => {
    track.mockClear();
    useCurrentChannelStore.setState({ currentChannelId: "channel-1" });
    useThreadPanelStore.setState({
      collapsed: false,
      openByChannel: { "channel-1": "task-1" },
    });
  });

  it("does nothing when the current channel has no open thread", () => {
    useThreadPanelStore.setState({ openByChannel: {} });

    toggleActivityPanel();

    expect(useThreadPanelStore.getState().collapsed).toBe(false);
    expect(track).not.toHaveBeenCalled();
  });

  it("does nothing when no channel is current", () => {
    useCurrentChannelStore.setState({ currentChannelId: null });

    toggleActivityPanel();

    expect(useThreadPanelStore.getState().collapsed).toBe(false);
    expect(track).not.toHaveBeenCalled();
  });

  it("collapses the open thread's panel and tracks the action", () => {
    toggleActivityPanel();

    expect(useThreadPanelStore.getState().collapsed).toBe(true);
    expect(track).toHaveBeenCalledWith("Channel action", {
      action_type: "collapse_thread",
      surface: "activity_panel",
      task_id: "task-1",
    });
  });

  it("expands an already-collapsed panel and tracks the action", () => {
    useThreadPanelStore.setState({ collapsed: true });

    toggleActivityPanel();

    expect(useThreadPanelStore.getState().collapsed).toBe(false);
    expect(track).toHaveBeenCalledWith("Channel action", {
      action_type: "expand_thread",
      surface: "activity_panel",
      task_id: "task-1",
    });
  });
});
