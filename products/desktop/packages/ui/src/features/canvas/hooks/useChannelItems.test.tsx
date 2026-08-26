import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Channel } from "./useChannels";

const mocks = vi.hoisted(() => ({
  channels: {
    channels: [] as {
      id: string;
      name: string;
      channelType: "public" | "personal";
      starred: boolean;
    }[],
    isLoading: true,
  },
  dashboards: { dashboards: [] as unknown[], isLoading: false },
  feed: { tasks: [] as unknown[], isLoading: false },
  filedTasks: { tasks: [] as { taskId: string }[], isLoading: false },
  allTasks: { data: [] as unknown[], isLoading: false },
  currentUser: undefined as { uuid: string; first_name?: string } | undefined,
  currentUserLoading: false,
  useTasks: vi.fn(),
  // Stable identities, mirroring the real hooks — a fresh function per render
  // would hide the very memoization this file asserts.
  setPinned: vi.fn(),
  setPinnedMany: vi.fn(),
  togglePin: vi.fn(),
  archiveTask: vi.fn(),
  navigate: vi.fn(),
  toastError: vi.fn(),
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
    setPinnedMany: mocks.setPinnedMany,
  }),
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: {
    error: mocks.toastError,
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));
// The session facts behind the status and environment filters. All three reach
// the host — for live sessions, viewed timestamps and workspaces — and this
// suite is about which items the hook builds, not what they say.
vi.mock("@posthog/ui/features/sidebar/useSidebarSessionMap", () => ({
  useSidebarSessionMap: () => new Map(),
}));
vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({ timestamps: {} }),
}));
vi.mock("@posthog/ui/features/workspace/useWorkspace", () => ({
  useWorkspaces: () => ({ data: undefined, isFetched: true }),
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

function channel(over: Partial<Channel> = {}): Channel {
  return {
    id: "c1",
    name: "eng",
    channelType: "public",
    starred: false,
    repositories: [],
    createdBy: null,
    ...over,
  };
}

function taskItem(id: string): ChannelItemModel {
  return {
    key: id,
    kind: "task",
    id,
    title: id,
    ts: 0,
    createdAt: 0,
    pinned: false,
    rawStatus: null,
    environment: null,
    source: null,
    needsInput: false,
    unread: false,
    authorUser: null,
    authorName: null,
    authorUuid: null,
    templateId: null,
    repository: null,
    branch: null,
    task: null,
  };
}

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

  it("filters the personal channel to the viewer once identity resolves", () => {
    mocks.channels = {
      channels: [channel({ name: "me", channelType: "personal" })],
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
      channels: [channel({ name: "me", channelType: "personal" })],
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

  it("shows everyone's items in a shared channel", () => {
    mocks.channels = { channels: [channel()], isLoading: false };
    mocks.dashboards = {
      dashboards: [
        canvas("mine", "Ada Lovelace"),
        canvas("theirs", "Grace Hopper"),
      ],
      isLoading: false,
    };
    mocks.currentUser = ME;

    const { result } = renderHook(() => useChannelItems("c1"));

    expect(result.current.items.map((i) => i.id).sort()).toEqual([
      "mine",
      "theirs",
    ]);
  });

  it("reports a channel that is not in the project rather than spinning", () => {
    mocks.channels = {
      channels: [channel({ id: "other" })],
      isLoading: false,
    };

    const { result } = renderHook(() => useChannelItems("deleted"));

    expect(result.current.channelMissing).toBe(true);
    expect(result.current.isLoading).toBe(false);
  });

  it("includes tasks filed into the space without duplicating feed tasks", () => {
    mocks.channels = {
      channels: [channel()],
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

  // A dragged session batch's pin request settles per-row and reports failures
  // in `failed` rather than rejecting, so the action must inspect that result —
  // a shared Promise.all would read a failed batch as success and stay silent.
  it.each([
    [
      "a partial pin failure",
      true,
      { succeeded: ["a"], failed: ["b"] },
      "1 pinned, 1 failed",
    ],
    [
      "a partial unpin failure",
      false,
      { succeeded: ["a"], failed: ["b"] },
      "1 unpinned, 1 failed",
    ],
    [
      "a fully successful batch",
      true,
      { succeeded: ["a", "b"], failed: [] },
      null,
    ],
  ] as const)(
    "reports %s from a session batch pin",
    async (_label, pinned, outcome, expectedMessage) => {
      mocks.channels = { channels: [channel()], isLoading: false };
      mocks.setPinnedMany.mockResolvedValue(outcome);

      const { result } = renderHook(() => useChannelItems("c1"));
      result.current.actions.setPinned([taskItem("a"), taskItem("b")], pinned);
      await mocks.setPinnedMany.mock.results.at(-1)?.value;

      expect(mocks.setPinnedMany).toHaveBeenCalledWith(["a", "b"], pinned);
      if (expectedMessage === null) {
        expect(mocks.toastError).not.toHaveBeenCalled();
      } else {
        expect(mocks.toastError).toHaveBeenCalledWith(expectedMessage);
      }
    },
  );
});
