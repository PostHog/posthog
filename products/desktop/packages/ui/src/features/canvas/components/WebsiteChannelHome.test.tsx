import { Theme } from "@radix-ui/themes";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

vi.mock("@posthog/ui/shell/rendererStorage", () => ({
  electronStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [{ id: "chan-1", name: "eng" }],
    isLoading: false,
  }),
}));
// The dock only exists off the chrome, so the layout is per-test state.
const layout = vi.hoisted(() => ({ channels: false }));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => layout.channels,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  PERSONAL_CHANNEL_NAME: "me",
  useTaskChannels: () => ({
    channels: [{ id: "chan-1", name: "eng" }],
    isLoading: false,
  }),
  useBackendChannel: () => ({
    channel: { id: "backend-1", name: "eng" },
    isLoading: false,
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelFeed", () => ({
  useChannelFeed: () => ({ tasks: [], isLoading: false }),
  channelFeedQueryKey: () => ["feed"],
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelFeedMessages", () => ({
  useChannelFeedMessages: () => ({ messages: [], isLoading: false }),
  channelCreationMessage: () => null,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFolderInstructions", () => ({
  useFolderInstructions: () => ({ data: undefined, isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTaskMutations: () => ({ fileTask: () => Promise.resolve() }),
}));
vi.mock("@posthog/ui/hooks/useSetHeaderContent", () => ({
  useSetHeaderContent: () => {},
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ setQueryData: vi.fn(), invalidateQueries: vi.fn() }),
}));
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));

// ThreadSidebar is the task dock under test; the rest of the channel chrome
// (feed rows, composer, intro) plays no part in the feed/sidebar exclusion.
vi.mock("@posthog/ui/features/canvas/components/ChannelFeedView", () => ({
  ChannelFeedView: () => <div data-testid="feed" />,
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelHomeComposer", () => ({
  ChannelHomeComposer: () => null,
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelIntro", () => ({
  ChannelIntro: () => null,
}));
vi.mock("@posthog/ui/features/canvas/components/CreateChannelModal", () => ({
  CreateChannelModal: () => null,
}));
vi.mock("@posthog/ui/features/canvas/components/ThreadSidebar", () => ({
  ThreadSidebar: () => <div data-testid="task-sidebar" />,
}));

import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { WebsiteChannelHome } from "./WebsiteChannelHome";

describe("WebsiteChannelHome", () => {
  beforeEach(() => {
    layout.channels = false;
    useThreadPanelStore.setState({
      openByChannel: {},
      collapsed: false,
      width: 360,
    });
  });

  it("drops a stale open thread so the feed can't show a task sidebar", () => {
    useThreadPanelStore.getState().openThread("chan-1", "task-1");
    render(
      <Theme>
        <WebsiteChannelHome channelId="chan-1" />
      </Theme>,
    );

    expect(screen.getByTestId("feed")).toBeTruthy();
    expect(screen.queryByTestId("task-sidebar")).toBeNull();
    expect(useThreadPanelStore.getState().openByChannel["chan-1"]).toBeNull();
  });

  it.each([
    { channels: false, docked: true },
    { channels: true, docked: false },
  ])(
    "thread opened from this feed docks=$docked when channels layout is $channels",
    ({ channels, docked }) => {
      layout.channels = channels;
      render(
        <Theme>
          <WebsiteChannelHome channelId="chan-1" />
        </Theme>,
      );

      act(() => {
        useThreadPanelStore.getState().openThread("chan-1", "task-1");
      });

      expect(Boolean(screen.queryByTestId("task-sidebar"))).toBe(docked);
      expect(screen.queryByTestId("feed")).toBeTruthy();
    },
  );
});
