import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useMemo } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const activityMocks = vi.hoisted(() => ({
  clearSelection: vi.fn(),
  selection: null as {
    kind: "task";
    id: string;
    taskId: string;
    channelId: string | null;
  } | null,
}));

vi.mock("@posthog/ui/features/canvas/stores/activityDetailStore", () => ({
  clearActivitySelection: activityMocks.clearSelection,
  useActivitySelection: () => activityMocks.selection,
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    channelTasks: {
      list: {
        queryOptions: () => ({ queryKey: ["ct"], queryFn: async () => [] }),
      },
    },
    workspace: {
      getAllTaskTimestamps: {
        queryKey: () => ["ts"],
        queryOptions: () => ({ queryKey: ["ts"], queryFn: async () => ({}) }),
      },
    },
  }),
  useHostTRPCClient: () => ({
    workspace: {
      markViewed: { mutate: vi.fn() },
      markActivity: { mutate: vi.fn() },
    },
  }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/canvas/hooks/useSelectedCanvasId", () => ({
  useSelectedCanvasId: () => undefined,
}));
vi.mock("@tanstack/react-router", () => ({
  // The route's own pane, which is where the header's writer lives.
  Outlet: () => <ActivityDetailPane />,
  useNavigate: () => vi.fn(),
  useSearch: () => ({}),
  useParams: () => ({ channelId: "chan-1", taskId: "task-1" }),
  useRouterState: ({
    select,
  }: {
    select: (s: {
      location: { pathname: string; href: string };
      matches: {
        routeId: string;
        fullPath: string;
        search: Record<string, unknown>;
      }[];
    }) => unknown;
  }) =>
    select({
      location: {
        pathname: "/spaces/chan-1/tasks/task-1",
        href: "/spaces/chan-1/tasks/task-1",
      },
      matches: [
        {
          routeId: "/spaces/$channelId/tasks/$taskId",
          // Activity's pane reads its selection off `/activity`'s search, which
          // this route is not — the pane renders its empty state, which is all
          // this test needs from it.
          fullPath: "/spaces/$channelId/tasks/$taskId",
          search: {},
        },
      ],
    }),
}));
vi.mock(
  "@posthog/ui/features/task-detail/components/TaskHeaderActions",
  () => ({
    TaskHeaderActions: () => <div />,
  }),
);
vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: () => ({
    data: [{ id: "task-1", title: "T", updated_at: "2026-01-01T00:00:00Z" }],
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTasks: () => ({ tasks: [], isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [{ id: "chan-1", name: "space" }] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useInboxActivityPreview", () => ({
  useInboxActivityPreview: () => ({ reports: [] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelStars", () => ({
  useChannelStarMutations: () => ({ star: vi.fn(), unstar: vi.fn() }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useDashboard: () => ({ dashboard: null }),
  useCanvasVersions: () => ({ versions: [] }),
  useDashboardMutations: () => ({}),
}));
vi.mock("@posthog/ui/features/sessions/components/useComments", () => ({
  useCommentsQuery: () => ({ data: [] }),
}));
vi.mock("@posthog/ui/features/canvas/stores/dashboardEditStore", () => ({
  useDashboardEditStore: () => vi.fn(),
  useIsDashboardEditing: () => false,
}));
vi.mock("@posthog/ui/features/canvas/components/NewCanvasMenu", () => ({
  NewCanvasMenu: () => null,
}));
vi.mock("@posthog/ui/features/canvas/freeform/CanvasFrameHost", () => ({
  CanvasFrameHost: () => null,
}));
vi.mock("@posthog/ui/features/navigation/components/RightPanel", () => ({
  RightPanel: () => null,
}));
vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({ markAsViewed: vi.fn() }),
}));
vi.mock("@posthog/ui/router/routeSkeletons", () => ({
  TaskDetailSkeleton: () => <div>skeleton</div>,
}));

// Stands in for the real task view, which cannot be imported here. The task
// identity is deliberately unstable, the way a live query's is mid-refetch.
let taskDetailRenders = 0;
vi.mock("@posthog/ui/features/task-detail/components/TaskDetail", () => ({
  TaskDetail: ({
    task,
    channelName,
  }: {
    task: { title: string };
    channelName?: string;
  }) => {
    taskDetailRenders += 1;
    const content = useMemo(
      () => <span>{`${channelName} / ${task.title}`}</span>,
      [channelName, task],
    );
    useSetHeaderContent(content);
    return <div>detail</div>;
  },
}));

import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { ActivityDetailPane } from "./ActivityDetailPane";
import { ShellLayout } from "./ShellLayout";
import { SpaceHeaderRow } from "./SpaceHeaderRow";

describe("SpaceHeaderRow", () => {
  beforeEach(() => {
    activityMocks.clearSelection.mockClear();
    activityMocks.selection = null;
  });

  it("keeps the header store off the layout that renders its writer", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ShellLayout />
      </QueryClientProvider>,
    );
    // A layout that subscribes to the header store blows the update depth here.
    expect(taskDetailRenders).toBeLessThan(20);
  });

  it("can close an Activity session before task actions resolve", () => {
    activityMocks.selection = {
      kind: "task",
      id: "activity-1",
      taskId: "task-1",
      channelId: null,
    };

    render(<SpaceHeaderRow />);

    fireEvent.click(screen.getByLabelText("Close activity item"));
    expect(activityMocks.clearSelection).toHaveBeenCalledOnce();
  });
});
