import type { TaskChannel } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getTaskChannels: vi.fn(),
  resolveTaskChannel: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

import { useChannelMutations, useChannels } from "./useChannels";

function taskChannel(id: string, name: string): TaskChannel {
  return {
    id,
    name,
    channel_type: "public",
    starred: false,
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
      await mutations.result.current.createChannel("beta");
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
      await mutations.result.current.createChannel("alpha");
    });

    // The duplicate-id guard keeps the list at one entry.
    expect(list.result.current.channels.map((c) => c.id)).toEqual(["1"]);
  });
});
