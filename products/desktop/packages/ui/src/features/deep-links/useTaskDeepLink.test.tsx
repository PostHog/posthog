import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openTask = vi.hoisted(() =>
  vi.fn().mockResolvedValue({
    success: true,
    data: { task: { id: "t1" }, workspace: null },
  }),
);
const getPendingDeepLink = vi.hoisted(() => vi.fn().mockResolvedValue(null));
const onOpenTask = vi.hoisted(() =>
  vi.fn(
    (
      _input?: unknown,
      _opts?: { onData?: (data: { taskId: string }) => void },
    ) => ({ unsubscribe: vi.fn() }),
  ),
);
const routerOpenTask = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const markAsViewed = vi.hoisted(() => vi.fn());
const bluebirdState = vi.hoisted(() => ({ enabled: true }));
const channelMapState = vi.hoisted(() => ({
  map: new Map<string, { id: string; name: string; path: string }>(),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({
    deepLink: {
      getPendingDeepLink: { query: getPendingDeepLink },
      onOpenTask: { subscribe: onOpenTask },
    },
  }),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (sel: (s: { status: string }) => unknown) =>
    sel({ status: "authenticated" }),
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTask: routerOpenTask,
}));
vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({ markAsViewed }),
}));
vi.mock("@posthog/di/react", () => ({
  useService: () => ({ openTask }),
}));
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: { scope: () => ({ info: vi.fn(), error: vi.fn(), warn: vi.fn() }) },
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => bluebirdState.enabled,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [], isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannelMap", () => ({
  useTaskChannelMap: () => channelMapState.map,
}));

import { useTaskDeepLink } from "./useTaskDeepLink";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useTaskDeepLink", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getPendingDeepLink.mockResolvedValue(null);
    bluebirdState.enabled = true;
    channelMapState.map = new Map();
  });

  const marketing = { id: "chan-1", name: "marketing", path: "/marketing" };

  // Both entry points (cold-start pending link, warm-start subscription event)
  // run the same routing dispatch: a channel-filed task opens in its /website
  // channel view, otherwise it falls back to /code — and only when the bluebird
  // flag is on.
  it.each([
    {
      name: "cold-start unfiled task → /code",
      trigger: "pending" as const,
      enabled: true,
      channel: null,
      expected: undefined,
    },
    {
      name: "cold-start channel-filed task → its channel view",
      trigger: "pending" as const,
      enabled: true,
      channel: marketing,
      expected: { channelId: "chan-1" },
    },
    {
      name: "cold-start filed task with flag off → /code",
      trigger: "pending" as const,
      enabled: false,
      channel: marketing,
      expected: undefined,
    },
    {
      name: "warm-start channel-filed task → its channel view",
      trigger: "warm" as const,
      enabled: true,
      channel: marketing,
      expected: { channelId: "chan-1" },
    },
  ])("$name", async ({ trigger, enabled, channel, expected }) => {
    bluebirdState.enabled = enabled;
    if (channel) channelMapState.map = new Map([["t1", channel]]);

    if (trigger === "pending") {
      getPendingDeepLink.mockResolvedValue({ taskId: "t1" });
      renderHook(() => useTaskDeepLink(), { wrapper });
    } else {
      renderHook(() => useTaskDeepLink(), { wrapper });
      // Drive the warm-start path through the subscription's onData callback.
      onOpenTask.mock.calls[0]?.[1]?.onData?.({ taskId: "t1" });
    }

    await waitFor(() =>
      expect(routerOpenTask).toHaveBeenCalledWith({ id: "t1" }, expected),
    );
    expect(openTask).toHaveBeenCalledWith("t1", undefined);
    expect(markAsViewed).toHaveBeenCalledWith("t1");
  });

  it("subscribes to warm-start open-task events", () => {
    renderHook(() => useTaskDeepLink(), { wrapper });
    expect(onOpenTask).toHaveBeenCalledTimes(1);
  });
});
