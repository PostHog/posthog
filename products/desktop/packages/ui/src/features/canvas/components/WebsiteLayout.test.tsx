import { Theme } from "@radix-ui/themes";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => false,
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    dashboards: { saveContext: { mutationKey: () => ["save-context"] } },
  }),
}));

const { useChannelTasks, useDashboard, useParams, usePathname, useTasks } =
  vi.hoisted(() => ({
    useChannelTasks: vi.fn(),
    useDashboard: vi.fn(),
    useParams: vi.fn(),
    usePathname: vi.fn(),
    useTasks: vi.fn(),
  }));

vi.mock("@tanstack/react-router", () => ({
  Outlet: () => null,
  useNavigate: () => vi.fn(),
  useParams,
  useRouterState: ({
    select,
  }: {
    select: (s: { location: { pathname: string } }) => string;
  }) => select({ location: { pathname: usePathname() } }),
}));

vi.mock(
  "@posthog/ui/features/task-detail/components/TaskHeaderActions",
  () => ({
    TaskHeaderActions: ({ task }: { task: { id: string } }) => (
      <div data-testid="task-header-actions">{task.id}</div>
    ),
  }),
);

vi.mock("@posthog/ui/features/tasks/useTasks", () => ({ useTasks }));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTasks,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [{ id: "chan-1", name: "project-bluebird" }],
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useDashboard,
  useDashboardMutations: () => ({}),
  useCanvasVersions: () => ({ versions: [{ taskId: "version-task" }] }),
}));
vi.mock("@posthog/ui/features/sessions/components/useComments", () => ({
  useCommentsQuery: () => ({
    data: [
      {
        id: "comment-1",
        created_at: "2026-01-01T00:00:00Z",
        content: "First",
        item_id: "canvas-1",
        item_context: { anchor: { kind: "document" } },
        scope: "desktop_canvas",
        source_comment: null,
        completed_at: null,
      },
      {
        id: "comment-2",
        created_at: "2026-01-01T00:01:00Z",
        content: "Second",
        item_id: "canvas-1",
        item_context: { anchor: { kind: "document" } },
        scope: "desktop_canvas",
        source_comment: null,
        completed_at: null,
      },
    ],
  }),
}));
vi.mock("@posthog/ui/features/canvas/stores/dashboardEditStore", () => ({
  useDashboardEditStore: (sel: (s: unknown) => unknown) =>
    sel({ setEditing: vi.fn() }),
  useIsDashboardEditing: () => false,
}));
vi.mock("@posthog/ui/features/canvas/components/NewCanvasMenu", () => ({
  NewCanvasMenu: () => null,
}));
vi.mock("@posthog/ui/features/canvas/freeform/CanvasFrameHost", () => ({
  CanvasFrameHost: () => null,
}));

import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import { WebsiteLayout } from "./WebsiteLayout";

function renderLayout({
  pathname,
  params,
  tasks = [{ id: "task-1", title: "Fix the bug" }],
  channelTaskIds = tasks.map((task) => task.id),
  dashboard,
}: {
  pathname: string;
  params: Record<string, string>;
  tasks?: { id: string; title: string }[];
  channelTaskIds?: string[];
  dashboard?: {
    name: string;
    templateId: string;
    generationTaskId: string | null;
  };
}) {
  usePathname.mockReturnValue(pathname);
  useParams.mockReturnValue(params);
  useTasks.mockReturnValue({ data: tasks });
  useChannelTasks.mockReturnValue({
    tasks: channelTaskIds.map((taskId) => ({ taskId })),
    isLoading: false,
  });
  useDashboard.mockReturnValue({ dashboard });
  useHeaderStore.setState({ content: <span>crumb</span> });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Theme>
        <WebsiteLayout />
      </Theme>
    </QueryClientProvider>,
  );
}

describe("WebsiteLayout task header actions", () => {
  it.each([
    ["while generating", "task-1"],
    ["after generation", null],
  ])(
    "shows the comment count and opens comments %s",
    (_label, generationTaskId) => {
      renderLayout({
        pathname: "/website/chan-1/dashboards/canvas-1",
        params: { channelId: "chan-1", dashboardId: "canvas-1" },
        dashboard: {
          name: "Launch",
          templateId: "freeform",
          generationTaskId,
        },
      });

      expect(
        screen.getByRole("button", { name: /Comments/ }),
      ).toHaveTextContent("Comments2");
      useCanvasChatPanelStore.setState({ collapsed: true, tab: "chat" });
      fireEvent.click(screen.getByRole("button", { name: /Comments/ }));
      expect(useCanvasChatPanelStore.getState()).toMatchObject({
        collapsed: false,
        tab: "comments",
      });
    },
  );

  it("renders the task action row on a channel task detail", () => {
    renderLayout({
      pathname: "/website/chan-1/tasks/task-1",
      params: { channelId: "chan-1", taskId: "task-1" },
    });
    expect(screen.getByTestId("task-header-actions")).toHaveTextContent(
      "task-1",
    );
  });

  it("does not render actions for a task filed to another channel", () => {
    renderLayout({
      pathname: "/website/chan-1/tasks/task-1",
      params: { channelId: "chan-1", taskId: "task-1" },
      channelTaskIds: ["other-task"],
    });
    expect(screen.queryByTestId("task-header-actions")).not.toBeInTheDocument();
  });

  it.each([
    ["channel home", "/website/chan-1", { channelId: "chan-1" }],
    ["new task", "/website/chan-1/new", { channelId: "chan-1" }],
  ])("does not render the action row on %s", (_label, pathname, params) => {
    renderLayout({ pathname, params });
    expect(screen.queryByTestId("task-header-actions")).not.toBeInTheDocument();
  });
});
