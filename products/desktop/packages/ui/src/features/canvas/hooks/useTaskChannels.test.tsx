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

import { useBackendChannel } from "./useTaskChannels";

function taskChannel(id: string, name: string): TaskChannel {
  return {
    id,
    name,
    channel_type: "public",
    created_at: "2026-01-01T00:00:00Z",
  };
}

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useBackendChannel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("stays loading from mount until the resolve lands, without a not-loading flash", async () => {
    mockClient.getTaskChannels.mockResolvedValue([]);
    let landResolve: (channel: TaskChannel) => void = () => {};
    mockClient.resolveTaskChannel.mockReturnValue(
      new Promise((resolve) => {
        landResolve = resolve;
      }),
    );

    // Record isLoading across every render: the identity of the channel is
    // unknown until the resolve lands, so no render in between may claim
    // "not loading" — callers would flash their empty state.
    const observed: boolean[] = [];
    const { result } = renderHook(
      () => {
        const state = useBackendChannel("mobile");
        observed.push(state.isLoading);
        return state;
      },
      { wrapper },
    );

    await waitFor(() =>
      expect(mockClient.resolveTaskChannel).toHaveBeenCalledWith("mobile"),
    );
    expect(observed).not.toContain(false);

    await act(async () => {
      landResolve(taskChannel("1", "mobile"));
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.channel?.id).toBe("1");
  });

  it("settles as not-loading after a failed resolve instead of retrying forever", async () => {
    mockClient.getTaskChannels.mockResolvedValue([]);
    // Reject asynchronously, like a real network failure — an immediate
    // rejection collapses the pending→error renders and would mask a retry
    // loop keyed on the pending flag flipping back.
    mockClient.resolveTaskChannel.mockImplementation(
      () =>
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error("backend down")), 1),
        ),
    );

    const { result } = renderHook(() => useBackendChannel("mobile"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.channel).toBeUndefined();

    // The failing POST must not hot-loop.
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(mockClient.resolveTaskChannel).toHaveBeenCalledTimes(1);
    expect(result.current.isLoading).toBe(false);
  });

  it("resolves a new name even after a previous name failed", async () => {
    mockClient.getTaskChannels.mockResolvedValue([]);
    mockClient.resolveTaskChannel.mockRejectedValueOnce(
      new Error("backend down"),
    );

    const { result, rerender } = renderHook(
      ({ name }: { name: string }) => useBackendChannel(name),
      { wrapper, initialProps: { name: "mobile" } },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.channel).toBeUndefined();

    mockClient.resolveTaskChannel.mockResolvedValue(taskChannel("2", "web"));
    rerender({ name: "web" });

    await waitFor(() => expect(result.current.channel?.id).toBe("2"));
    expect(mockClient.resolveTaskChannel).toHaveBeenLastCalledWith("web");
  });

  it("maps the personal name onto the personal channel without resolving", async () => {
    const personal: TaskChannel = {
      ...taskChannel("p1", "me"),
      channel_type: "personal",
    };
    mockClient.getTaskChannels.mockResolvedValue([personal]);

    const { result } = renderHook(() => useBackendChannel("me"), { wrapper });

    await waitFor(() => expect(result.current.channel?.id).toBe("p1"));
    expect(result.current.isLoading).toBe(false);
    expect(mockClient.resolveTaskChannel).not.toHaveBeenCalled();
  });
});
