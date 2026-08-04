import type { TaskChannel } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getTaskChannels: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

import { useTaskChannels } from "./useTaskChannels";

function taskChannel(
  id: string,
  name: string,
  channelType: TaskChannel["channel_type"] = "public",
): TaskChannel {
  return {
    id,
    name,
    channel_type: channelType,
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

describe("useTaskChannels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("surfaces the personal channel from the list", async () => {
    const personal = taskChannel("p1", "me", "personal");
    mockClient.getTaskChannels.mockResolvedValue([
      taskChannel("1", "growth"),
      personal,
    ]);

    const { result } = renderHook(() => useTaskChannels(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.channels.map((c) => c.id)).toEqual(["1", "p1"]);
    expect(result.current.personalChannel).toBe(personal);
  });

  it("reports loading (and no personal channel) until the list lands", () => {
    mockClient.getTaskChannels.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useTaskChannels(), { wrapper });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.channels).toEqual([]);
    expect(result.current.personalChannel).toBeUndefined();
  });
});
