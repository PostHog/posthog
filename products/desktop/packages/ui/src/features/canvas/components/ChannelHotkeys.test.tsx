import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  channelsLayout: true,
  slots: [] as { id: string; name: string; path: string }[],
  navigateToChannel: vi.fn(),
  view: { type: "task-input" } as { type: string; taskId?: string },
  tasks: [] as { id: string; title: string }[],
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => mocks.channelsLayout,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useStarredChannelSlots", () => ({
  useStarredChannelSlots: () => ({
    slots: mocks.slots,
    rest: [],
    slotFor: () => undefined,
  }),
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToChannel: (...args: unknown[]) => mocks.navigateToChannel(...args),
}));
vi.mock("@posthog/ui/router/useAppView", () => ({
  useAppView: () => mocks.view,
}));
vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: () => ({ data: mocks.tasks }),
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: vi.fn() },
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { ChannelHotkeys } from "./ChannelHotkeys";

function press(digit: string, modifiers: Partial<KeyboardEventInit> = {}) {
  document.dispatchEvent(
    new KeyboardEvent("keydown", {
      key: digit,
      code: `Digit${digit}`,
      bubbles: true,
      cancelable: true,
      ...modifiers,
    }),
  );
}

describe("ChannelHotkeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.channelsLayout = true;
    mocks.slots = [
      { id: "me-id", name: "me", path: "/me" },
      { id: "eng-id", name: "eng", path: "/eng" },
    ];
    mocks.view = { type: "task-input" };
    mocks.tasks = [];
    useCurrentChannelStore.setState({ currentChannelId: null });
    useSpacesSidebarStore.setState({ watchList: [] });
  });

  // The regression: this component is rendered ALONE — no sidebar at all.
  // Binding the keys inside the sidebar left them unowned exactly when the
  // channel list hadn't resolved yet.
  it("switches channels without the sidebar being mounted", () => {
    render(<ChannelHotkeys />);

    press("1", { metaKey: true });

    expect(mocks.navigateToChannel).toHaveBeenCalledWith("me-id");
    expect(useCurrentChannelStore.getState().currentChannelId).toBe("me-id");
  });

  it("maps slot 2 to the first starred channel", () => {
    render(<ChannelHotkeys />);
    press("2", { metaKey: true });
    expect(mocks.navigateToChannel).toHaveBeenCalledWith("eng-id");
  });

  // mod+0 belongs to the host's "Actual Size" accelerator.
  it("ignores mod+0", () => {
    render(<ChannelHotkeys />);
    press("0", { metaKey: true });
    expect(mocks.navigateToChannel).not.toHaveBeenCalled();
  });

  // ctrl+1-9 is the editor-panel tab switcher on every platform.
  it("leaves pure ctrl presses to the panel tab switcher", () => {
    render(<ChannelHotkeys />);
    press("1", { ctrlKey: true });
    expect(mocks.navigateToChannel).not.toHaveBeenCalled();
  });

  it("does nothing for a slot with no channel behind it", () => {
    mocks.slots = [{ id: "me-id", name: "me", path: "/me" }];
    render(<ChannelHotkeys />);
    press("5", { metaKey: true });
    expect(mocks.navigateToChannel).not.toHaveBeenCalled();
  });

  it("stays out of the way when the layout is off", () => {
    mocks.channelsLayout = false;
    render(<ChannelHotkeys />);
    press("1", { metaKey: true });
    expect(mocks.navigateToChannel).not.toHaveBeenCalled();
  });

  // ⌘⇧W watches the task you're looking at — the keyboard twin of the row menu.
  it("adds the current task to the watch list on mod+shift+w", () => {
    mocks.view = { type: "task-detail", taskId: "task-1" };
    mocks.tasks = [{ id: "task-1", title: "Fix the thing" }];
    render(<ChannelHotkeys />);

    press("w", { metaKey: true, shiftKey: true });

    const watchList = useSpacesSidebarStore.getState().watchList;
    expect(watchList.map((e) => e.id)).toEqual(["task-1"]);
    expect(watchList[0].title).toBe("Fix the thing");
  });

  // Nowhere obvious to watch → no-op, rather than watching a phantom.
  it("does nothing on mod+shift+w outside a task detail", () => {
    mocks.view = { type: "task-input" };
    render(<ChannelHotkeys />);

    press("w", { metaKey: true, shiftKey: true });

    expect(useSpacesSidebarStore.getState().watchList).toEqual([]);
  });
});
