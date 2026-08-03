import type { TaskChannel } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getTaskChannels: vi.fn(),
  starTaskChannel: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { useChannelStars, useChannelStarToggle } from "./useChannelStars";
import type { Channel } from "./useChannels";

function taskChannel(id: string, name: string, starred = false): TaskChannel {
  return {
    id,
    name,
    channel_type: "public",
    starred,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function channel(id: string, name: string, starred = false): Channel {
  return { id, name, channelType: "public", starred };
}

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useChannelStars", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("collects the ids of channels the user starred", async () => {
    mockClient.getTaskChannels.mockResolvedValue([
      taskChannel("1", "alpha", true),
      taskChannel("2", "beta", false),
    ]);

    const { result } = renderHook(() => useChannelStars(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect([...result.current.starredChannelIds]).toEqual(["1"]);
  });

  it("stars an unstarred channel, updating the cache immediately", async () => {
    mockClient.getTaskChannels.mockResolvedValue([taskChannel("1", "alpha")]);

    const stars = renderHook(() => useChannelStars(), { wrapper });
    await waitFor(() => expect(stars.result.current.isLoading).toBe(false));
    expect(stars.result.current.starredChannelIds.size).toBe(0);

    mockClient.starTaskChannel.mockResolvedValue(undefined);
    // Hang the refetch so only the optimistic cache write is exercised.
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const toggle = renderHook(
      () => useChannelStarToggle(channel("1", "alpha")),
      {
        wrapper,
      },
    );
    expect(toggle.result.current.isStarred).toBe(false);

    await act(async () => {
      toggle.result.current.toggleStar();
    });

    expect(mockClient.starTaskChannel).toHaveBeenCalledWith("1", true);
    await waitFor(() =>
      expect(stars.result.current.starredChannelIds.has("1")).toBe(true),
    );
  });

  it("unstars a starred channel by clearing its flag", async () => {
    mockClient.getTaskChannels.mockResolvedValue([
      taskChannel("1", "alpha", true),
    ]);

    const stars = renderHook(() => useChannelStars(), { wrapper });
    await waitFor(() => expect(stars.result.current.isLoading).toBe(false));
    expect(stars.result.current.starredChannelIds.has("1")).toBe(true);

    mockClient.starTaskChannel.mockResolvedValue(undefined);
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const toggle = renderHook(
      () => useChannelStarToggle(channel("1", "alpha", true)),
      { wrapper },
    );
    expect(toggle.result.current.isStarred).toBe(true);

    await act(async () => {
      toggle.result.current.toggleStar();
    });

    expect(mockClient.starTaskChannel).toHaveBeenCalledWith("1", false);
    await waitFor(() =>
      expect(stars.result.current.starredChannelIds.has("1")).toBe(false),
    );
  });
});
