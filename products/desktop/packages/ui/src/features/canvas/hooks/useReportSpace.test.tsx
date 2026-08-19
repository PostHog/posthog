// @vitest-environment jsdom

import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useReportSpace } from "./useReportSpace";

const createChannel = vi.fn(async () => ({ id: "general-id" }));
let currentProjectId = 1;
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
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (
    selector: (state: { currentProjectId: number }) => number,
  ) => selector({ currentProjectId }),
}));

describe("useReportSpace", () => {
  beforeEach(() => {
    channelsState.channels = [];
    currentProjectId = 1;
    createChannel.mockClear();
  });

  it("provisions the default report space once and resolves its id", async () => {
    const { rerender, result } = renderHook(() => useReportSpace());
    await waitFor(() => expect(createChannel).toHaveBeenCalledTimes(1));
    expect(createChannel).toHaveBeenCalledWith("general", { star: true });

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
    expect(result.current.reportSpaceId).toBe("general-id");
  });

  it("does not provision or expose the report space when disabled", () => {
    channelsState.channels = [
      {
        id: "general-id",
        name: "general",
        channelType: "public",
        starred: false,
      },
    ];

    const { result } = renderHook(() => useReportSpace(false));

    expect(createChannel).not.toHaveBeenCalled();
    expect(result.current).toEqual({ reportSpaceId: null, isLoading: false });
  });

  it("provisions again after the current project changes", async () => {
    const { rerender } = renderHook(() => useReportSpace());
    await waitFor(() => expect(createChannel).toHaveBeenCalledTimes(1));

    currentProjectId = 2;
    rerender();

    await waitFor(() => expect(createChannel).toHaveBeenCalledTimes(2));
  });
});
