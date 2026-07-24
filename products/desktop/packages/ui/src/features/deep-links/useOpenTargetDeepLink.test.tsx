import type { NotificationTarget } from "@posthog/platform/notifications";
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
const getPendingOpenTarget = vi.hoisted(() => vi.fn().mockResolvedValue(null));
const onOpenTarget = vi.hoisted(() =>
  vi.fn(
    (
      _input?: unknown,
      _opts?: { onData?: (data: NotificationTarget) => void },
    ) => ({ unsubscribe: vi.fn() }),
  ),
);
const routerOpenTask = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const navigateToChannelDashboard = vi.hoisted(() => vi.fn());
const markAsViewed = vi.hoisted(() => vi.fn());

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({
    deepLink: {
      getPendingOpenTarget: { query: getPendingOpenTarget },
      onOpenTarget: { subscribe: onOpenTarget },
    },
  }),
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToChannelDashboard,
  setOpenTargetHandler: vi.fn(),
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTask: routerOpenTask }));
vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({ markAsViewed }),
}));
vi.mock("@posthog/di/react", () => ({ useService: () => ({ openTask }) }));
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: { scope: () => ({ info: vi.fn(), error: vi.fn(), warn: vi.fn() }) },
}));
vi.mock("@posthog/ui/primitives/toast", () => ({ toast: { error: vi.fn() } }));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [], isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannelMap", () => ({
  useTaskChannelMap: () => new Map(),
}));

import { useOpenTargetDeepLink } from "./useOpenTargetDeepLink";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

const taskTarget: NotificationTarget = { kind: "task", taskId: "t1" };
const canvasTarget: NotificationTarget = {
  kind: "canvas",
  channelId: "chan-1",
  dashboardId: "dash-1",
};

describe("useOpenTargetDeepLink", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getPendingOpenTarget.mockResolvedValue(null);
  });

  it("routes a warm-start task target through the open-task saga", async () => {
    renderHook(() => useOpenTargetDeepLink(), { wrapper });
    onOpenTarget.mock.calls[0]?.[1]?.onData?.(taskTarget);
    await waitFor(() => expect(openTask).toHaveBeenCalledWith("t1", undefined));
    expect(routerOpenTask).toHaveBeenCalledWith({ id: "t1" }, undefined);
  });

  it("routes a warm-start canvas target to its dashboard", () => {
    renderHook(() => useOpenTargetDeepLink(), { wrapper });
    onOpenTarget.mock.calls[0]?.[1]?.onData?.(canvasTarget);
    expect(navigateToChannelDashboard).toHaveBeenCalledWith("chan-1", "dash-1");
  });

  it("drains a pending target queued before the listener was live", async () => {
    getPendingOpenTarget.mockResolvedValue(canvasTarget);
    renderHook(() => useOpenTargetDeepLink(), { wrapper });
    await waitFor(() =>
      expect(navigateToChannelDashboard).toHaveBeenCalledWith(
        "chan-1",
        "dash-1",
      ),
    );
  });

  it("subscribes once to warm-start open-target events", () => {
    renderHook(() => useOpenTargetDeepLink(), { wrapper });
    expect(onOpenTarget).toHaveBeenCalledTimes(1);
  });
});
