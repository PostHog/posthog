import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { useMemo } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    dashboards: { saveContext: { mutationKey: () => ["save-context"] } },
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
vi.mock("@tanstack/react-router", () => ({
  Outlet: () => null,
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
  useRouterState: ({
    select,
  }: {
    select: (s: { location: { pathname: string } }) => string;
  }) => select({ location: { pathname: "/website/home" } }),
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

// Stands in for the real task view, which cannot be imported here (its module
// graph reaches the workspace client). What matters is the shape it shares with
// the real one: it publishes the title row through the header store, and it
// derives that row from the task it was handed. The task identity is
// deliberately unstable, the way a live query's is mid-refetch — which is what
// turns a subscription in the wrong place into a runaway.
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

import { useActivityDetailStore } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { useNavRailStore } from "@posthog/ui/features/canvas/stores/navRailStore";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { WebsiteLayout } from "./WebsiteLayout";

describe("SpaceHeaderRow", () => {
  it("keeps the header store off the layout that renders its writer", () => {
    useNavRailStore.setState({ pane: "activity" });
    useActivityDetailStore.setState({
      selected: { id: "a1", taskId: "task-1", channelId: "chan-1" } as never,
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <WebsiteLayout />
      </QueryClientProvider>,
    );
    // If the layout subscribes to the header store again, every title write
    // re-renders the screen that wrote it and this blows React's update depth.
    expect(taskDetailRenders).toBeLessThan(20);
  });
});
