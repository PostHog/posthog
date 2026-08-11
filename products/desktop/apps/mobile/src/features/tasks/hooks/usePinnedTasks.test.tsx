import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

const { mockGetPinnedTaskIds, mockSetTaskPinned } = vi.hoisted(() => ({
  mockGetPinnedTaskIds: vi.fn(),
  mockSetTaskPinned: vi.fn(),
}));

vi.mock("@/lib/posthogApiClient", () => ({
  getPostHogApiClient: () => ({
    getPinnedTaskIds: mockGetPinnedTaskIds,
    setTaskPinned: mockSetTaskPinned,
  }),
}));
vi.mock("@/lib/logger", () => {
  const mockLogger = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    scope: () => mockLogger,
  };
  return { logger: mockLogger };
});
vi.mock("@/features/auth", () => ({
  useAuthStore: () => ({ projectId: 2, oauthAccessToken: "token" }),
}));

import { usePinnedTasks } from "./usePinnedTasks";

function renderPinned() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  let latest: ReturnType<typeof usePinnedTasks> | null = null;

  function Harness() {
    latest = usePinnedTasks();
    return null;
  }

  act(() => {
    create(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(Harness),
      ),
    );
  });
  return {
    current: () => {
      if (!latest) throw new Error("harness did not render");
      return latest;
    },
    queryClient,
  };
}

async function waitUntil(cond: () => boolean) {
  for (let i = 0; i < 40; i++) {
    if (cond()) return;
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
  throw new Error("condition not met within the wait budget");
}

describe("usePinnedTasks", () => {
  it("exposes the server's pin list and membership checks", async () => {
    mockGetPinnedTaskIds.mockResolvedValue(["a", "b"]);
    const harness = renderPinned();
    await waitUntil(() => harness.current().pinnedTaskIds.length === 2);

    expect(harness.current().pinnedTaskIds).toEqual(["a", "b"]);
    expect(harness.current().isPinned("a")).toBe(true);
    expect(harness.current().isPinned("z")).toBe(false);
  });

  it("pins an unpinned task and settles on the server's new list", async () => {
    mockGetPinnedTaskIds
      .mockResolvedValueOnce(["a"])
      .mockResolvedValue(["b", "a"]);
    mockSetTaskPinned.mockResolvedValue(true);
    const harness = renderPinned();
    await waitUntil(() => harness.current().pinnedTaskIds.length === 1);

    act(() => harness.current().togglePin("b"));

    await waitUntil(() => harness.current().pinnedTaskIds.length === 2);
    expect(harness.current().pinnedTaskIds).toEqual(["b", "a"]);
    expect(mockSetTaskPinned).toHaveBeenCalledWith("b", true);
  });

  it("rolls back the optimistic update when the server rejects", async () => {
    mockGetPinnedTaskIds.mockResolvedValue(["a"]);
    mockSetTaskPinned.mockRejectedValue(new Error("nope"));
    const harness = renderPinned();
    await waitUntil(() => harness.current().pinnedTaskIds.length === 1);

    act(() => harness.current().togglePin("b"));

    // Rejection rolls the optimistic entry back off the list.
    await waitUntil(() => mockSetTaskPinned.mock.calls.length === 1);
    await waitUntil(() => harness.current().pinnedTaskIds.length === 1);
    expect(harness.current().pinnedTaskIds).toEqual(["a"]);
  });

  it("unpins a pinned task", async () => {
    mockGetPinnedTaskIds.mockResolvedValueOnce(["a"]).mockResolvedValue([]);
    mockSetTaskPinned.mockResolvedValue(false);
    const harness = renderPinned();
    await waitUntil(() => harness.current().pinnedTaskIds.length === 1);

    act(() => harness.current().togglePin("a"));

    await waitUntil(() => harness.current().pinnedTaskIds.length === 0);
    expect(mockSetTaskPinned).toHaveBeenCalledWith("a", false);
  });
});
