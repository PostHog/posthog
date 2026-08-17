// @vitest-environment jsdom

import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useGeneralSpace } from "./useGeneralSpace";

const createChannel = vi.fn(async () => ({ id: "general-id" }));
const channelsState: {
  channels: Array<{
    id: string;
    name: string;
    channelType: "public";
    starred: boolean;
  }>;
} = {
  channels: [],
};

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: channelsState.channels, isLoading: false }),
  useChannelMutations: () => ({ createChannel }),
}));

describe("useGeneralSpace", () => {
  beforeEach(() => {
    channelsState.channels = [];
    createChannel.mockClear();
  });

  it("provisions general once and resolves it from the channel list", async () => {
    const { rerender, result } = renderHook(() => useGeneralSpace());
    await waitFor(() => expect(createChannel).toHaveBeenCalledTimes(1));

    rerender();
    expect(createChannel).toHaveBeenCalledTimes(1);

    channelsState.channels = [
      {
        id: "general-id",
        name: "general",
        channelType: "public",
        starred: false,
      },
    ];
    rerender();
    expect(result.current.generalSpaceId).toBe("general-id");
  });
});
