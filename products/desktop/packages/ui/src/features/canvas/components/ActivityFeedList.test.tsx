import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchNextPage: vi.fn(),
  hasNextPage: true,
  isFetchingNextPage: false,
  items: [] as TaskActivityItem[],
  markRead: vi.fn(),
  unreadCount: 0,
}));

vi.mock("@posthog/quill", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
  Button: ({
    children,
    disabled,
    onClick,
    "aria-label": ariaLabel,
  }: {
    children: ReactNode;
    disabled?: boolean;
    onClick?: () => void;
    "aria-label"?: string;
  }) => (
    <button
      type="button"
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  ),
  DropdownMenu: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  DropdownMenuItem: ({
    children,
    disabled,
    onClick,
  }: {
    children: ReactNode;
    disabled?: boolean;
    onClick?: () => void;
  }) => (
    <button type="button" disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
  DropdownMenuTrigger: ({ render }: { render: ReactElement }) => render,
  Empty: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  EmptyDescription: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  EmptyHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  EmptyMedia: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  EmptyTitle: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  MenuLabel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Label: ({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) => (
    <label htmlFor={htmlFor}>{children}</label>
  ),
  PopoverContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  Spinner: () => <div>Loading</div>,
  Switch: ({
    checked,
    onCheckedChange,
  }: {
    checked: boolean;
    onCheckedChange: (checked: boolean) => void;
  }) => (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onCheckedChange(!checked)}
    >
      Unreads
    </button>
  ),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: null }),
}));
vi.mock("@posthog/ui/features/canvas/components/ActivityRow", () => ({
  ActivityRow: ({
    item,
    onMarkRead,
  }: {
    item: TaskActivityItem;
    onMarkRead: (item: TaskActivityItem) => void;
  }) => (
    <button type="button" onClick={() => onMarkRead(item)}>
      Activity row
    </button>
  ),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead", () => ({
  useMarkTaskActivityRead: () => ({
    mutate: mocks.markRead,
    isPending: false,
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useLocalDayStart", () => ({
  useLocalDayStart: () => new Date(2026, 7, 25).getTime(),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskActivity", () => ({
  useTaskActivity: () => ({
    items: mocks.items,
    unreadCount: mocks.unreadCount,
    isLoading: false,
    hasNextPage: mocks.hasNextPage,
    isFetchingNextPage: mocks.isFetchingNextPage,
    fetchNextPage: mocks.fetchNextPage,
  }),
}));
vi.mock("@posthog/ui/primitives/hooks/useInView", () => ({
  useInView: () => [vi.fn(), true],
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { ActivityFeedList } from "./ActivityFeedList";

describe("ActivityFeedList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.hasNextPage = true;
    mocks.isFetchingNextPage = false;
    mocks.items = [];
    mocks.unreadCount = 0;
    useActivityFilterStore.setState({ unreadsOnly: false });
  });

  it("loads the next page when the bottom sentinel is visible", async () => {
    render(<ActivityFeedList />);

    await waitFor(() => expect(mocks.fetchNextPage).toHaveBeenCalledOnce());
  });

  it("does not load when there is no next page", async () => {
    mocks.hasNextPage = false;
    render(<ActivityFeedList />);

    await waitFor(() => expect(mocks.fetchNextPage).not.toHaveBeenCalled());
  });

  it("marks the exact comment activity as read", () => {
    mocks.items = [
      {
        id: "activity-1",
        taskId: "task-1",
        activityAt: "2026-08-07T00:00:00Z",
        activityKind: "owned_item_comment",
        commentId: "comment-1",
        isUnread: true,
      } as TaskActivityItem,
    ];

    render(<ActivityFeedList />);
    fireEvent.click(screen.getByText("Activity row"));

    expect(mocks.markRead).toHaveBeenCalledWith([
      {
        task_id: "task-1",
        seen_before: "2026-08-07T00:00:00Z",
        activity_id: "activity-1",
      },
    ]);
  });

  it("puts the mark-all action in a menu after the unreads switch", () => {
    mocks.unreadCount = 1;
    mocks.items = [
      {
        id: "activity-1",
        taskId: "task-1",
        activityAt: "2026-08-07T00:00:00Z",
        activityKind: "completed",
        isUnread: true,
      } as TaskActivityItem,
    ];

    render(<ActivityFeedList />);

    const unreadsSwitch = screen.getByRole("switch", { name: "Unreads" });
    const activityActions = screen.getByRole("button", {
      name: "Activity actions",
    });
    expect(unreadsSwitch.compareDocumentPosition(activityActions)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );

    fireEvent.click(screen.getByRole("button", { name: "Mark all as read" }));
    expect(mocks.markRead).toHaveBeenCalledWith([
      {
        task_id: "task-1",
        seen_before: "2026-08-07T00:00:00Z",
      },
    ]);
  });

  it("drops read activity while the unreads filter is on", () => {
    mocks.items = [
      {
        id: "read-activity",
        taskId: "task-1",
        activityAt: "2026-08-07T00:00:00Z",
        activityKind: "mention",
        isUnread: false,
      } as TaskActivityItem,
      {
        id: "unread-activity",
        taskId: "task-2",
        activityAt: "2026-08-07T00:01:00Z",
        activityKind: "mention",
        isUnread: true,
      } as TaskActivityItem,
    ];

    render(<ActivityFeedList />);
    expect(screen.getAllByText("Activity row")).toHaveLength(2);

    fireEvent.click(screen.getByRole("switch"));

    expect(screen.getAllByText("Activity row")).toHaveLength(1);
  });

  it("groups the panel rows by local calendar day", () => {
    mocks.hasNextPage = false;
    mocks.items = [
      {
        id: "today",
        taskId: "task-1",
        activityAt: new Date(2026, 7, 25, 10).toISOString(),
        activityKind: "completed",
        isUnread: false,
      } as TaskActivityItem,
      {
        id: "yesterday",
        taskId: "task-2",
        activityAt: new Date(2026, 7, 24, 10).toISOString(),
        activityKind: "completed",
        isUnread: false,
      } as TaskActivityItem,
    ];

    render(<ActivityFeedList />);

    const rows = screen.getAllByText("Activity row");
    expect(screen.getByText("Today").compareDocumentPosition(rows[0])).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(screen.getByText("Yesterday").compareDocumentPosition(rows[1])).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
});
