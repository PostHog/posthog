import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const channelsResult = vi.hoisted(() => ({
  current: {
    channels: [] as { id: string; name: string; path: string }[],
    isLoading: true,
  },
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => channelsResult.current,
}));

import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useCurrentChannel } from "./useCurrentChannel";

function channel(id: string, name: string) {
  return { id, name, path: `/${name}` };
}

describe("useCurrentChannel", () => {
  beforeEach(() => {
    useCurrentChannelStore.setState({ currentChannelId: null });
    channelsResult.current = { channels: [], isLoading: true };
  });

  it("holds a scoped id while the channel list is still loading", () => {
    useCurrentChannelStore.setState({ currentChannelId: "c1" });
    channelsResult.current = { channels: [], isLoading: true };

    const { result } = renderHook(() => useCurrentChannel({ enabled: true }));

    // A pending list is not evidence of absence — clearing here would unscope
    // the sidebar on every cold load.
    expect(useCurrentChannelStore.getState().currentChannelId).toBe("c1");
    expect(result.current.currentChannelId).toBeNull();
  });

  it("resolves the channel once the list lands", () => {
    useCurrentChannelStore.setState({ currentChannelId: "c1" });
    channelsResult.current = {
      channels: [channel("c1", "eng")],
      isLoading: false,
    };

    const { result } = renderHook(() => useCurrentChannel({ enabled: true }));

    expect(result.current.currentChannelId).toBe("c1");
    expect(result.current.channels.map((c) => c.name)).toEqual(["eng"]);
    // Resolving must not clear a channel that does exist.
    expect(useCurrentChannelStore.getState().currentChannelId).toBe("c1");
  });

  it("clears a channel the loaded list does not contain", () => {
    // The shape of a project switch: the store still names the old project's
    // channel, and the refetched list has never heard of it.
    useCurrentChannelStore.setState({ currentChannelId: "from-old-project" });
    channelsResult.current = {
      channels: [channel("c9", "new")],
      isLoading: false,
    };

    const { result } = renderHook(() => useCurrentChannel({ enabled: true }));

    expect(useCurrentChannelStore.getState().currentChannelId).toBeNull();
    expect(result.current.currentChannelId).toBeNull();
  });

  it("unscopes entirely when the layout is disabled", () => {
    useCurrentChannelStore.setState({ currentChannelId: "c1" });
    channelsResult.current = {
      channels: [channel("c1", "eng")],
      isLoading: false,
    };

    renderHook(() => useCurrentChannel({ enabled: false }));

    expect(useCurrentChannelStore.getState().currentChannelId).toBeNull();
  });
});
