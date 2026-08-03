import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  channels: {
    channels: [] as { id: string; name: string; path: string }[],
    isLoading: true,
  },
  dashboards: { dashboards: [] as unknown[], isLoading: false },
  feed: { tasks: [] as unknown[], isLoading: false },
  filedTasks: { tasks: [] as { taskId: string }[], isLoading: false },
  allTasks: { data: [] as unknown[], isLoading: false },
  currentUser: undefined as { uuid: string; first_name?: string } | undefined,
  currentUserLoading: false,
  useBackendChannel: vi.fn(),
  useTasks: vi.fn(),
  // Stable identities, mirroring the real hooks — a fresh function per render
  // would hide the very memoization this file asserts.
  setPinned: vi.fn(),
  togglePin: vi.fn(),
  archiveTask: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => mocks.channels,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useDashboards: () => mocks.dashboards,
  useDashboardMutations: () => ({ setPinned: mocks.setPinned }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelFeed", () => ({
  useChannelFeed: () => mocks.feed,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTasks: () => mocks.filedTasks,
}));
vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: (filters: unknown) => {
    mocks.useTasks(filters);
    return mocks.allTasks;
  },
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  PERSONAL_CHANNEL_NAME: "me",
  useBackendChannel: (name: string | undefined) => {
    mocks.useBackendChannel(name);
    return { channel: undefined, isLoading: false };
  },
}));
vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => new Set<string>(),
}));
vi.mock("@posthog/ui/features/archive/useArchiveTask", () => ({
  useArchiveTask: () => ({ archiveTask: mocks.archiveTask }),
}));
vi.mock("@posthog/ui/features/sidebar/usePinnedTasks", () => ({
  usePinnedTasks: () => ({
    pinnedTaskIds: new Set<string>(),
    togglePin: mocks.togglePin,
  }),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => undefined,
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({
    data: mocks.currentUser,
    isLoading: mocks.currentUserLoading,
  }),
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => mocks.navigate,
}));

import { useChannelItems } from "./useChannelItems";

const ME = { uuid: "me-uuid", first_name: "Ada", last_name: "Lovelace" };

function canvas(id: string, createdBy?: string, createdByUuid?: string) {
  return {
    id,
    channelId: "c1",
    name: id,
    templateId: "freeform",
    createdBy,
    createdByUuid,
    createdAt: 0,
    updatedAt: 1_000,
  };
}

describe("useChannelItems", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.channels = { channels: [], isLoading: true };
    mocks.dashboards = { dashboards: [], isLoading: false };
    mocks.feed = { tasks: [], isLoading: false };
    mocks.filedTasks = { tasks: [], isLoading: false };
    mocks.allTasks = { data: [], isLoading: false };
    mocks.currentUser = undefined;
    mocks.currentUserLoading = false;
  });

  // The bug this pins: a placeholder channel name reaches useBackendChannel,
  // whose resolve-or-create effect provisions a real backend channel named
  // after the placeholder on every cold load.
  it("never hands a channel name to the resolver while the list is pending", () => {
    renderHook(() => useChannelItems("c1"));
    expect(mocks.useBackendChannel).toHaveBeenCalledWith(undefined);
    expect(mocks.useBackendChannel).not.toHaveBeenCalledWith("channel");
  });

  it("reports loading and no items until the channel's identity is known", () => {
    // Dashboards are keyed on the route param so they can resolve first —
    // which is exactly how foreign items used to flash into #me.
    mocks.dashboards = {
      dashboards: [canvas("d1", "Grace Hopper")],
      isLoading: false,
    };

    const { result } = renderHook(() => useChannelItems("c1"));

    expect(result.current.items).toEqual([]);
    expect(result.current.isLoading).toBe(true);
  });

  it("passes the real name through once the list lands", () => {
    mocks.channels = {
      channels: [{ id: "c1", name: "eng", path: "/eng" }],
      isLoading: false,
    };
    renderHook(() => useChannelItems("c1"));
    expect(mocks.useBackendChannel).toHaveBeenCalledWith("eng");
  });

  it("filters the personal channel to the viewer once identity resolves", () => {
    mocks.channels = {
      channels: [{ id: "c1", name: "me", path: "/me" }],
      isLoading: false,
    };
    mocks.dashboards = {
      dashboards: [
        canvas("mine", "Ada Lovelace", ME.uuid),
        canvas("theirs", "Grace Hopper", "other-uuid"),
      ],
      isLoading: false,
    };
    mocks.currentUser = ME;

    const { result } = renderHook(() => useChannelItems("c1"));

    expect(result.current.items.map((i) => i.id)).toEqual(["mine"]);
  });

  it("keeps #me private while the viewer is loading", () => {
    mocks.channels = {
      channels: [{ id: "c1", name: "me", path: "/me" }],
      isLoading: false,
    };
    mocks.dashboards = {
      dashboards: [
        canvas("mine", "Ada Lovelace"),
        canvas("theirs", "Grace Hopper"),
      ],
      isLoading: false,
    };
    mocks.currentUser = undefined;
    mocks.currentUserLoading = true;

    const { result } = renderHook(() => useChannelItems("c1"));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.items).toEqual([]);
  });

  it("reports a channel that is not in the project rather than spinning", () => {
    mocks.channels = {
      channels: [{ id: "other", name: "eng", path: "/eng" }],
      isLoading: false,
    };

    const { result } = renderHook(() => useChannelItems("deleted"));

    expect(result.current.channelMissing).toBe(true);
    expect(result.current.isLoading).toBe(false);
  });

  it("includes tasks filed into the space without duplicating feed tasks", () => {
    mocks.channels = {
      channels: [{ id: "c1", name: "eng", path: "/eng" }],
      isLoading: false,
    };
    const filedTask = {
      id: "task-1",
      title: "Filed task",
      updated_at: "2026-07-28T12:00:00Z",
      latest_run: null,
      created_by: null,
    };
    mocks.filedTasks = {
      tasks: [{ taskId: "task-1" }],
      isLoading: false,
    };
    mocks.allTasks = { data: [filedTask], isLoading: false };
    mocks.feed = { tasks: [], isLoading: false };

    const { result, rerender } = renderHook(() => useChannelItems("c1"));

    expect(result.current.items.map((item) => item.id)).toEqual(["task-1"]);
    expect(mocks.useTasks).toHaveBeenCalledWith({ showAllUsers: true });

    mocks.feed = { tasks: [filedTask], isLoading: false };
    rerender();
    expect(result.current.items.map((item) => item.id)).toEqual(["task-1"]);
  });
});
