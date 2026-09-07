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
const readMirror = vi.hoisted(() => vi.fn());
const reseedMirror = vi.hoisted(() => vi.fn());
const historyPush = vi.hoisted(() => vi.fn());
const getRouterOrNull = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/browser-tabs/tabsSync", () => ({
  readMirror,
  reseedMirror,
}));
vi.mock("@posthog/ui/router/routerRef", () => ({ getRouterOrNull }));

const seeded = (): { windows: unknown[]; tabs: unknown[] } => ({
  windows: [
    { id: "window-1", isPrimary: true, bounds: null, activeTabId: "tab-1" },
  ],
  tabs: [],
});

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
    readMirror.mockReturnValue(seeded());
    reseedMirror.mockResolvedValue(null);
    getRouterOrNull.mockReturnValue({
      history: { location: { state: {} }, push: historyPush },
    });
  });

  it("routes a warm-start task target through the open-task saga", async () => {
    renderHook(() => useOpenTargetDeepLink(), { wrapper });
    onOpenTarget.mock.calls[0]?.[1]?.onData?.(taskTarget);
    await waitFor(() => expect(openTask).toHaveBeenCalledWith("t1", undefined));
    expect(routerOpenTask).toHaveBeenCalledWith({ id: "t1" }, undefined);
  });

  it("routes a warm-start canvas target to its dashboard", async () => {
    renderHook(() => useOpenTargetDeepLink(), { wrapper });
    onOpenTarget.mock.calls[0]?.[1]?.onData?.(canvasTarget);
    await waitFor(() =>
      expect(navigateToChannelDashboard).toHaveBeenCalledWith(
        "chan-1",
        "dash-1",
      ),
    );
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

  const targetTab = {
    id: "tab-9",
    windowId: "window-1",
    href: "/tasks/t1",
    viewState: { title: "Task t1" },
    dashboardId: null,
    taskId: "t1",
    channelId: null,
    channelSection: null,
    appView: null,
    position: 1000,
    scrollState: null,
    createdAt: 1,
    lastActiveAt: 1,
  };

  it("focuses the tab that already shows the target instead of opening a copy", () => {
    readMirror.mockReturnValue({
      windows: seeded().windows,
      tabs: [targetTab],
    });

    renderHook(() => useOpenTargetDeepLink(), { wrapper });
    onOpenTarget.mock.calls[0]?.[1]?.onData?.(taskTarget);

    expect(historyPush).toHaveBeenCalledWith("/tasks/t1", { tabId: "tab-9" });
    expect(openTask).not.toHaveBeenCalled();
    expect(routerOpenTask).not.toHaveBeenCalled();
  });

  it("focuses the target's tab after a cold-start mirror reseed", async () => {
    let reseeded = false;
    readMirror.mockImplementation(() =>
      reseeded
        ? { windows: seeded().windows, tabs: [targetTab] }
        : { windows: [], tabs: [] },
    );
    reseedMirror.mockImplementation(async () => {
      reseeded = true;
      return { windows: seeded().windows, tabs: [targetTab] };
    });
    getPendingOpenTarget.mockResolvedValue(taskTarget);

    renderHook(() => useOpenTargetDeepLink(), { wrapper });

    await waitFor(() =>
      expect(historyPush).toHaveBeenCalledWith("/tasks/t1", {
        tabId: "tab-9",
      }),
    );
    expect(openTask).not.toHaveBeenCalled();
  });
});
