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
}));
vi.mock(
  "@posthog/ui/features/sessions/components/ArtifactDocumentCommentAction",
  () => ({
    ArtifactDocumentCommentAction: ({
      taskId,
      onCreated,
    }: {
      taskId: string;
      onCreated?: (commentId: string) => void;
    }) => (
      <button
        type="button"
        data-testid="canvas-comment-action"
        onClick={() => onCreated?.("comment-1")}
      >
        {taskId}
      </button>
    ),
  }),
);
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
    generationTaskId: string;
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
  it("offers document comments on a task-generated canvas", () => {
    renderLayout({
      pathname: "/website/chan-1/dashboards/canvas-1",
      params: { channelId: "chan-1", dashboardId: "canvas-1" },
      dashboard: {
        name: "Launch",
        templateId: "freeform",
        generationTaskId: "task-1",
      },
    });

    expect(screen.getByTestId("canvas-comment-action")).toHaveTextContent(
      "task-1",
    );
    useCanvasChatPanelStore.setState({ collapsed: true, tab: "chat" });
    fireEvent.click(screen.getByTestId("canvas-comment-action"));
    expect(useCanvasChatPanelStore.getState()).toMatchObject({
      collapsed: false,
      tab: "comments",
    });
  });

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
