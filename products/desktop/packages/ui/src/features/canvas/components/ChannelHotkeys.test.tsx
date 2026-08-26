import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  channelsLayout: true,
  /** With tabs on, ⌘1-9 switches tabs and this component yields the keys. */
  spacesTabs: false,
  slots: [] as { id: string; name: string; path: string }[],
  navigateToChannel: vi.fn(),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => mocks.channelsLayout,
}));
vi.mock("@posthog/ui/features/feature-flags/useSpacesTabs", () => ({
  useSpacesTabs: () => mocks.spacesTabs,
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
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import {
  showChannelPane,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSidebarSearchStore } from "@posthog/ui/features/canvas/stores/sidebarSearchStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { ChannelHotkeys } from "./ChannelHotkeys";

function press(key: string, modifiers: Partial<KeyboardEventInit> = {}) {
  document.dispatchEvent(
    new KeyboardEvent("keydown", {
      key,
      code: /^\d$/.test(key) ? `Digit${key}` : `Key${key.toUpperCase()}`,
      bubbles: true,
      cancelable: true,
      ...modifiers,
    }),
  );
}

describe("ChannelHotkeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.spacesTabs = false;
    mocks.channelsLayout = true;
    mocks.slots = [
      { id: "me-id", name: "me", path: "/me" },
      { id: "eng-id", name: "eng", path: "/eng" },
    ];
    useCurrentChannelStore.setState({ currentChannelId: null });
    useSidebarSearchStore.setState({
      focusRequest: 0,
    });
    useSidebarStore.setState({ open: false });
    showChannelPane();
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

  it("yields the keys to the tab strip when tabs are on", () => {
    mocks.spacesTabs = true;
    mocks.slots = [{ id: "personal", name: "me", path: "/spaces/personal" }];
    render(<ChannelHotkeys />);

    press("1");

    expect(mocks.navigateToChannel).not.toHaveBeenCalled();
  });

  it("stays out of the way when the layout is off", () => {
    mocks.channelsLayout = false;
    render(<ChannelHotkeys />);
    press("1", { metaKey: true });
    expect(mocks.navigateToChannel).not.toHaveBeenCalled();
  });

  it("opens the space list and requests focus for its search", () => {
    render(<ChannelHotkeys />);

    press("s", { metaKey: true, shiftKey: true });

    expect(useSidebarStore.getState().open).toBe(true);
    expect(useChannelPaneStore.getState().pane).toBe("list");
    expect(useSidebarSearchStore.getState().focusRequest).toBe(1);
  });
});
