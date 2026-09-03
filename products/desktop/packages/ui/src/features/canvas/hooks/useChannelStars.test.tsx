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
import { TASK_CHANNELS_QUERY_KEY } from "./useTaskChannels";

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
  return {
    id,
    name,
    channelType: "public",
    starred,
    repositories: [],
    createdBy: null,
  };
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

  it("settles to the user's LAST click when star/unstar resolve out of order", async () => {
    mockClient.getTaskChannels.mockResolvedValue([taskChannel("1", "alpha")]);
    // Keep the post-mutation refetch from overwriting the optimistic write
    // with a stale snapshot, which is exactly what hides the race.
    let resolveStar!: () => void;
    let resolveUnstar!: () => void;
    mockClient.starTaskChannel
      .mockImplementationOnce(
        () =>
          new Promise<void>((res) => {
            resolveStar = res;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<void>((res) => {
            resolveUnstar = res;
          }),
      );

    // Seed the shared channels cache via the list hook, then hang any refetch
    // so only the mutation writes (not a refetched snapshot) decide the cache.
    const stars = renderHook(() => useChannelStars(), { wrapper });
    await waitFor(() => expect(stars.result.current.isLoading).toBe(false));
    await waitFor(() =>
      expect(queryClient.getQueryData(TASK_CHANNELS_QUERY_KEY)).toBeTruthy(),
    );
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    // Two rapid toggles: star then unstar, modelled with explicit isStarred so
    // both mutations fire (a single component's stale closure is a separate UI
    // quirk; this isolates the resolve-order race).
    const first = renderHook(
      () => useChannelStarToggle(channel("1", "alpha", false)),
      { wrapper },
    );
    const second = renderHook(
      () => useChannelStarToggle(channel("1", "alpha", true)),
      { wrapper },
    );

    act(() => {
      first.result.current.toggleStar(); // star
      second.result.current.toggleStar(); // unstar
    });
    // Optimistic write applies immediately from the last click.
    await waitFor(() =>
      expect(
        queryClient
          .getQueryData<{ id: string; starred: boolean }[]>(
            TASK_CHANNELS_QUERY_KEY,
          )
          ?.find((c) => c.id === "1")?.starred,
      ).toBe(false),
    );

    // Resolve in REVERSE order: unstar first, star last. With the last-resolved
    // wins bug, the star (wrong, older intent) would overwrite the cache.
    await act(async () => {
      resolveUnstar();
      resolveStar();
    });

    const cached = queryClient
      .getQueryData<{ id: string; starred: boolean }[]>(TASK_CHANNELS_QUERY_KEY)
      ?.find((c) => c.id === "1");
    // The cache must reflect the last click (unstar), not the late star.
    expect(cached?.starred).toBe(false);
  });
});
