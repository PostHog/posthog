import type { TaskChannel } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getTaskChannels: vi.fn(),
  updateTaskChannelRepositories: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

import {
  TASK_CHANNELS_QUERY_KEY,
  useTaskChannels,
  useUpdateTaskChannelRepositories,
} from "./useTaskChannels";

function taskChannel(
  id: string,
  name: string,
  channelType: TaskChannel["channel_type"] = "public",
  systemRole?: TaskChannel["system_role"],
): TaskChannel {
  return {
    id,
    name,
    channel_type: channelType,
    starred: false,
    created_at: "2026-01-01T00:00:00Z",
    system_role: systemRole ?? null,
  };
}

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useTaskChannels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("surfaces the personal and general channels from the list", async () => {
    const personal = taskChannel("p1", "me", "personal", "personal");
    const general = taskChannel("g1", "general", "public", "general");
    mockClient.getTaskChannels.mockResolvedValue([
      taskChannel("1", "growth"),
      general,
      personal,
    ]);

    const { result } = renderHook(() => useTaskChannels(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.channels.map((c) => c.id)).toEqual(["1", "g1", "p1"]);
    expect(result.current.personalChannel).toEqual({
      ...personal,
      name: "personal",
    });
    expect(result.current.generalChannel).toEqual(general);
  });

  it("reports loading (and no personal or general channel) until the list lands", () => {
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useTaskChannels(), { wrapper });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.channels).toEqual([]);
    expect(result.current.personalChannel).toBeUndefined();
    expect(result.current.generalChannel).toBeUndefined();
  });

  it("updates repository links immediately while the request is pending", async () => {
    const channel = taskChannel("1", "growth");
    queryClient.setQueryData<TaskChannel[]>(TASK_CHANNELS_QUERY_KEY, [channel]);
    let finishUpdate: (updated: TaskChannel) => void = () => {};
    mockClient.updateTaskChannelRepositories.mockReturnValue(
      new Promise((resolve) => {
        finishUpdate = resolve;
      }),
    );

    const { result } = renderHook(() => useUpdateTaskChannelRepositories(), {
      wrapper,
    });
    act(() => {
      result.current.mutate({
        channelId: channel.id,
        githubIntegration: 42,
        repositories: ["posthog/posthog"],
      });
    });

    await waitFor(() => expect(result.current.isPending).toBe(true));
    expect(
      queryClient.getQueryData<TaskChannel[]>(TASK_CHANNELS_QUERY_KEY),
    ).toEqual([
      {
        ...channel,
        github_integration: 42,
        repositories: ["posthog/posthog"],
      },
    ]);

    await act(async () => {
      finishUpdate({
        ...channel,
        github_integration: 42,
        repositories: ["posthog/posthog"],
      });
    });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(mockClient.updateTaskChannelRepositories).toHaveBeenCalledWith(
      "1",
      42,
      ["posthog/posthog"],
    );
  });
});
