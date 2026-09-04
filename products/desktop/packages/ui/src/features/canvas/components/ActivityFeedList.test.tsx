import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import type { SignalReport } from "@posthog/shared/types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchNextPage: vi.fn(),
  hasNextPage: true,
  isFetchingNextPage: false,
  items: [] as TaskActivityItem[],
  markRead: vi.fn(),
  inboxReportCount: 0,
  inboxReports: [] as SignalReport[],
  reportOpened: vi.fn(),
  unreadCount: 0,
}));

vi.mock("@posthog/quill", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@posthog/quill")>()),
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
vi.mock("@posthog/ui/features/canvas/components/ActivityActionsMenu", () => ({
  ActivityActionsMenu: ({ onMarkAllRead }: { onMarkAllRead: () => void }) => (
    <>
      <button type="button" aria-label="Activity actions" />
      <button type="button" onClick={onMarkAllRead}>
        Mark all as read
      </button>
    </>
  ),
}));
vi.mock("@posthog/ui/features/canvas/components/ActivityRow", async () => {
  const { ActivityRowSurface } = await import(
    "@posthog/ui/features/canvas/components/ActivityRowSurface"
  );
  return {
    ActivityRow: ({
      item,
      onMarkRead,
      onActivate,
      asOption,
      optionValue,
    }: {
      item: TaskActivityItem;
      onMarkRead: (item: TaskActivityItem) => void;
      onActivate: (item: TaskActivityItem) => void;
      asOption?: boolean;
      optionValue?: string;
    }) => (
      <ActivityRowSurface
        asOption={asOption}
        optionValue={optionValue}
        onClick={() => {
          onMarkRead(item);
          onActivate(item);
        }}
      >
        <span>Activity row</span>
        <span>{item.taskTitle}</span>
      </ActivityRowSurface>
    ),
  };
});
vi.mock(
  "@posthog/ui/features/canvas/components/InboxActivityOverflowRow",
  async () => {
    const { ActivityRowSurface } = await import(
      "@posthog/ui/features/canvas/components/ActivityRowSurface"
    );
    return {
      InboxActivityOverflowRow: ({
        count,
        onOpened,
        asOption,
        optionValue,
      }: {
        count: number;
        onOpened?: () => void;
        asOption?: boolean;
        optionValue?: string;
      }) => (
        <ActivityRowSurface
          asOption={asOption}
          optionValue={optionValue}
          onClick={onOpened}
        >
          View {count} more reports
        </ActivityRowSurface>
      ),
    };
  },
);
vi.mock("@posthog/ui/features/canvas/components/InboxActivityRow", async () => {
  const { ActivityRowSurface } = await import(
    "@posthog/ui/features/canvas/components/ActivityRowSurface"
  );
  return {
    InboxActivityRow: ({
      report,
      onOpened,
      asOption,
      optionValue,
      onActivate,
    }: {
      report: SignalReport;
      onOpened?: () => void;
      asOption?: boolean;
      optionValue?: string;
      onActivate?: (report: SignalReport) => void;
    }) => (
      <ActivityRowSurface
        asOption={asOption}
        optionValue={optionValue}
        onClick={() => {
          if (onActivate) {
            onActivate(report);
          } else {
            mocks.reportOpened();
          }
          onOpened?.();
        }}
      >
        Report row {report.id}
      </ActivityRowSurface>
    ),
  };
});
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
vi.mock("@posthog/ui/features/canvas/hooks/useInboxActivityPreview", () => ({
  useInboxActivityPreview: () => ({
    reports: mocks.inboxReports,
    totalCount: mocks.inboxReportCount,
    isLoading: false,
    isIncluded: true,
  }),
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxSourceFilterOptions", () => ({
  useInboxSourceFilterOptions: () => [],
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
    mocks.inboxReportCount = 0;
    mocks.inboxReports = [];
    mocks.unreadCount = 0;
    useActivityFilterStore.setState({
      unreadsOnly: false,
      mentionsEnabled: true,
    });
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
    mocks.inboxReportCount = 1;
    mocks.inboxReports = [
      {
        id: "report-1",
        updated_at: "2026-08-07T00:02:00Z",
      } as SignalReport,
    ];

    render(<ActivityFeedList />);
    expect(screen.getAllByText("Activity row")).toHaveLength(2);
    expect(screen.getByText("Report row report-1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch"));

    expect(screen.getAllByText("Activity row")).toHaveLength(1);
    expect(screen.queryByText("Report row report-1")).toBeNull();
  });

  it("hides task activity when mentions are excluded", () => {
    useActivityFilterStore.setState({ mentionsEnabled: false });
    mocks.items = [
      {
        id: "mention-1",
        taskId: "task-1",
        activityAt: "2026-08-07T00:00:00Z",
        activityKind: "mention",
        isUnread: true,
      } as TaskActivityItem,
    ];
    mocks.inboxReportCount = 1;
    mocks.inboxReports = [
      {
        id: "report-1",
        updated_at: "2026-08-07T00:01:00Z",
      } as SignalReport,
    ];

    render(<ActivityFeedList />);

    expect(screen.queryByText("Activity row")).toBeNull();
    expect(screen.getByText("Report row report-1")).toBeInTheDocument();
    expect(mocks.fetchNextPage).not.toHaveBeenCalled();
  });

  it("interleaves the inbox preview by date and links to the remaining reports", () => {
    mocks.hasNextPage = false;
    mocks.items = [
      {
        id: "task-1",
        taskId: "task-1",
        activityAt: new Date(2026, 7, 25, 9).toISOString(),
        activityKind: "completed",
        isUnread: false,
      } as TaskActivityItem,
    ];
    mocks.inboxReportCount = 5;
    mocks.inboxReports = [
      {
        id: "report-newer",
        updated_at: new Date(2026, 7, 25, 10).toISOString(),
      } as SignalReport,
      {
        id: "report-older",
        updated_at: new Date(2026, 7, 25, 8).toISOString(),
      } as SignalReport,
    ];

    render(<ActivityFeedList />);

    const newerReport = screen.getByText("Report row report-newer");
    const task = screen.getByText("Activity row");
    const olderReport = screen.getByText("Report row report-older");
    expect(newerReport.compareDocumentPosition(task)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(task.compareDocumentPosition(olderReport)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(screen.getByText("View 3 more reports")).toBeInTheDocument();
  });

  it("filters tasks and reports from the activity search", () => {
    mocks.hasNextPage = false;
    mocks.items = [
      {
        id: "task-billing",
        taskId: "task-billing",
        taskTitle: "Fix billing dashboard",
        channelName: "growth",
        activityAt: "2026-08-25T10:00:00Z",
        activityKind: "completed",
        isUnread: false,
      } as TaskActivityItem,
      {
        id: "task-onboarding",
        taskId: "task-onboarding",
        taskTitle: "Update onboarding",
        channelName: "product",
        activityAt: "2026-08-25T09:00:00Z",
        activityKind: "completed",
        isUnread: false,
      } as TaskActivityItem,
    ];
    mocks.inboxReportCount = 1;
    mocks.inboxReports = [
      {
        id: "report-checkout",
        title: "Checkout conversion dropped",
        updated_at: "2026-08-25T11:00:00Z",
      } as SignalReport,
    ];

    render(<ActivityFeedList />);
    fireEvent.change(screen.getByLabelText("Search activity"), {
      target: { value: "billing" },
    });

    expect(screen.getByText("Fix billing dashboard")).toBeInTheDocument();
    expect(screen.queryByText("Update onboarding")).toBeNull();
    expect(screen.queryByText("Report row report-checkout")).toBeNull();
  });

  it("walks every activity row from the search input and opens the highlighted row", async () => {
    const user = userEvent.setup();
    const onActivate = vi.fn();
    const onReportActivate = vi.fn();
    const onOpened = vi.fn();
    mocks.hasNextPage = false;
    mocks.items = [
      {
        id: "task-keyboard",
        taskId: "task-keyboard",
        taskTitle: "Keyboard task",
        activityAt: "2026-08-25T10:00:00Z",
        activityKind: "completed",
        isUnread: false,
      } as TaskActivityItem,
    ];
    mocks.inboxReportCount = 2;
    mocks.inboxReports = [
      {
        id: "report-keyboard",
        title: "Keyboard report",
        updated_at: "2026-08-25T09:00:00Z",
      } as SignalReport,
    ];

    render(
      <ActivityFeedList
        onActivate={onActivate}
        onReportActivate={onReportActivate}
        onOpened={onOpened}
      />,
    );

    expect(screen.getAllByRole("option")).toHaveLength(3);
    await user.click(screen.getByLabelText("Search activity"));
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    expect(onActivate).not.toHaveBeenCalled();
    expect(onReportActivate).toHaveBeenCalledWith(mocks.inboxReports[0]);
    expect(mocks.reportOpened).not.toHaveBeenCalled();
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
