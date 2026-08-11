import type { TaskChannel } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getTaskChannels: vi.fn(),
  resolveTaskChannel: vi.fn(),
  starTaskChannel: vi.fn(),
  renameTaskChannel: vi.fn(),
  deleteTaskChannel: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

import { useChannelMutations, useChannels } from "./useChannels";
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

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useChannelMutations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("shows the created channel immediately, before the refetch resolves", async () => {
    // Seed the list with one existing channel.
    mockClient.getTaskChannels.mockResolvedValue([taskChannel("1", "alpha")]);

    const list = renderHook(() => useChannels(), { wrapper });
    await waitFor(() => expect(list.result.current.isLoading).toBe(false));
    expect(list.result.current.channels.map((c) => c.name)).toEqual(["alpha"]);

    // Make the create return the new channel, but hang any subsequent refetch
    // so we can prove the list updates without waiting on it.
    const created = taskChannel("2", "beta");
    mockClient.resolveTaskChannel.mockResolvedValue(created);
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const mutations = renderHook(() => useChannelMutations(), { wrapper });
    await act(async () => {
      await mutations.result.current.createChannel("beta", { star: false });
    });

    // The new channel is present from the optimistic cache write, sorted
    // alphabetically alongside the existing one — without the hung refetch
    // having resolved.
    await waitFor(() =>
      expect(list.result.current.channels.map((c) => c.name)).toEqual([
        "alpha",
        "beta",
      ]),
    );
  });

  it("does not duplicate a channel the poll already landed", async () => {
    // The poll has already surfaced the channel we're about to create.
    const existing = taskChannel("1", "alpha");
    mockClient.getTaskChannels.mockResolvedValue([existing]);

    const list = renderHook(() => useChannels(), { wrapper });
    await waitFor(() => expect(list.result.current.isLoading).toBe(false));
    expect(list.result.current.channels.map((c) => c.id)).toEqual(["1"]);

    // Resolve returns the same id (resolve-or-create is idempotent); hang the
    // refetch so only the optimistic cache write is exercised.
    mockClient.resolveTaskChannel.mockResolvedValue(existing);
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const mutations = renderHook(() => useChannelMutations(), { wrapper });
    await act(async () => {
      await mutations.result.current.createChannel("alpha", { star: false });
    });

    // The duplicate-id guard keeps the list at one entry.
    expect(list.result.current.channels.map((c) => c.id)).toEqual(["1"]);
  });

  // A backend that ignores `star` on create is the case the follow-up call
  // exists for; the other two rows keep it from firing when it would either be
  // wasted or would star against the user's choice.
  it.each([
    ["a backend that ignored the create flag", true, false, true],
    ["a backend that starred on create", true, true, false],
    ["the toggle off", false, false, false],
  ])(
    "asks the star endpoint for the new channel only when needed: %s",
    async (_case, star, starredOnCreate, expectStarCall) => {
      // The sidebar has loaded and holds no spaces, so this name is new.
      queryClient.setQueryData(TASK_CHANNELS_QUERY_KEY, []);
      mockClient.resolveTaskChannel.mockResolvedValue(
        taskChannel("1", "alpha", starredOnCreate),
      );
      mockClient.starTaskChannel.mockResolvedValue(undefined);

      const mutations = renderHook(() => useChannelMutations(), { wrapper });
      let channel: { starred: boolean } | undefined;
      await act(async () => {
        channel = await mutations.result.current.createChannel("alpha", {
          star,
        });
      });

      expect(mockClient.starTaskChannel).toHaveBeenCalledTimes(
        expectStarCall ? 1 : 0,
      );
      if (expectStarCall) {
        expect(mockClient.starTaskChannel).toHaveBeenCalledWith("1", true);
      }
      expect(channel?.starred).toBe(star);
    },
  );

  it("leaves the star alone when the list it would check has not loaded", async () => {
    // Nothing has fetched the list, so an existing unstarred space and a brand
    // new one are indistinguishable here. Starring the wrong one is the costlier
    // mistake, so the fallback stands down.
    mockClient.resolveTaskChannel.mockResolvedValue(taskChannel("1", "alpha"));

    const mutations = renderHook(() => useChannelMutations(), { wrapper });
    await act(async () => {
      await mutations.result.current.createChannel("alpha", { star: true });
    });

    expect(mockClient.starTaskChannel).not.toHaveBeenCalled();
  });

  it("applies a rename before the server round-trip resolves", async () => {
    mockClient.getTaskChannels.mockResolvedValue([
      taskChannel("1", "alpha"),
      taskChannel("2", "beta"),
    ]);
    const list = renderHook(() => useChannels(), { wrapper });
    await waitFor(() => expect(list.result.current.isLoading).toBe(false));
    // Freeze both the rename call and any trailing refetch, so the rename can
    // only show through the optimistic cache write.
    let resolveRename: (channel: TaskChannel) => void = () => {};
    mockClient.renameTaskChannel.mockReturnValue(
      new Promise<TaskChannel>((resolve) => {
        resolveRename = resolve;
      }),
    );
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const mutations = renderHook(() => useChannelMutations(), { wrapper });
    let pending: Promise<unknown> | undefined;
    await act(async () => {
      pending = mutations.result.current.renameChannel("2", "gamma");
    });
    // The server call is still in flight, so the rename can only be visible
    // through the optimistic cache write.
    await waitFor(() =>
      expect(list.result.current.channels.map((c) => c.name)).toEqual([
        "alpha",
        "gamma",
      ]),
    );

    await act(async () => {
      resolveRename(taskChannel("2", "gamma"));
      await pending;
    });
    expect(list.result.current.channels.map((c) => c.name)).toEqual([
      "alpha",
      "gamma",
    ]);
  });

  it("restores the old name when a rename fails", async () => {
    mockClient.getTaskChannels.mockResolvedValue([taskChannel("1", "alpha")]);
    const list = renderHook(() => useChannels(), { wrapper });
    await waitFor(() => expect(list.result.current.isLoading).toBe(false));
    mockClient.renameTaskChannel.mockRejectedValue(new Error("nope"));
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const mutations = renderHook(() => useChannelMutations(), { wrapper });
    await act(async () => {
      await expect(
        mutations.result.current.renameChannel("1", "beta"),
      ).rejects.toThrow("nope");
    });
    expect(list.result.current.channels.map((c) => c.name)).toEqual(["alpha"]);
  });

  it("removes a deleted space from the list before the round-trip resolves", async () => {
    mockClient.getTaskChannels.mockResolvedValue([
      taskChannel("1", "alpha"),
      taskChannel("2", "beta"),
    ]);
    const list = renderHook(() => useChannels(), { wrapper });
    await waitFor(() => expect(list.result.current.isLoading).toBe(false));
    let resolveDelete: () => void = () => {};
    mockClient.deleteTaskChannel.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveDelete = () => resolve(undefined);
      }),
    );
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const mutations = renderHook(() => useChannelMutations(), { wrapper });
    let pending: Promise<unknown> | undefined;
    await act(async () => {
      pending = mutations.result.current.deleteChannel("1");
    });
    // The server call is still in flight, so the removal can only be visible
    // through the optimistic cache write.
    await waitFor(() =>
      expect(list.result.current.channels.map((c) => c.name)).toEqual(["beta"]),
    );

    await act(async () => {
      resolveDelete();
      await pending;
    });
    expect(list.result.current.channels.map((c) => c.name)).toEqual(["beta"]);
  });

  it("restores a deleted space when the delete fails", async () => {
    mockClient.getTaskChannels.mockResolvedValue([taskChannel("1", "alpha")]);
    const list = renderHook(() => useChannels(), { wrapper });
    await waitFor(() => expect(list.result.current.isLoading).toBe(false));
    mockClient.deleteTaskChannel.mockRejectedValue(new Error("nope"));
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const mutations = renderHook(() => useChannelMutations(), { wrapper });
    await act(async () => {
      await expect(mutations.result.current.deleteChannel("1")).rejects.toThrow(
        "nope",
      );
    });
    expect(list.result.current.channels.map((c) => c.name)).toEqual(["alpha"]);
  });

  it("leaves the star alone when the name resolves a space that already exists", async () => {
    // The list the create form was filled against already holds the name, so
    // this is a resolve, not a creation — the user's own star stands.
    const existing = taskChannel("1", "alpha");
    mockClient.getTaskChannels.mockResolvedValue([existing]);
    mockClient.resolveTaskChannel.mockResolvedValue(existing);

    const list = renderHook(() => useChannels(), { wrapper });
    await waitFor(() => expect(list.result.current.isLoading).toBe(false));

    const mutations = renderHook(() => useChannelMutations(), { wrapper });
    await act(async () => {
      await mutations.result.current.createChannel("alpha", { star: true });
    });

    expect(mockClient.starTaskChannel).not.toHaveBeenCalled();
  });
});
