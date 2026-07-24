import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { useChannelTasks, useParams, usePathname, useTasks } = vi.hoisted(
  () => ({
    useChannelTasks: vi.fn(),
    useParams: vi.fn(),
    usePathname: vi.fn(),
    useTasks: vi.fn(),
  }),
);

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
  useDashboard: () => ({ dashboard: undefined }),
  useDashboardMutations: () => ({}),
}));
vi.mock("@posthog/ui/features/canvas/stores/dashboardEditStore", () => ({
  useDashboardEditStore: (sel: (s: unknown) => unknown) =>
    sel({ setEditing: vi.fn() }),
  useIsDashboardEditing: () => false,
}));
vi.mock("@posthog/ui/features/canvas/stores/freeformChatStore", () => ({
  useFreeformChatStore: (sel: (s: unknown) => unknown) =>
    sel({ revert: vi.fn(), goToLatest: vi.fn() }),
  useFreeformThread: () => ({
    code: "",
    versions: [],
    currentVersionId: null,
    isSaving: false,
  }),
}));
vi.mock("@posthog/ui/features/canvas/components/NewCanvasMenu", () => ({
  NewCanvasMenu: () => null,
}));
vi.mock("@posthog/ui/features/canvas/freeform/CanvasFrameHost", () => ({
  CanvasFrameHost: () => null,
}));

import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import { WebsiteLayout } from "./WebsiteLayout";

function renderLayout({
  pathname,
  params,
  tasks = [{ id: "task-1", title: "Fix the bug" }],
  channelTaskIds = tasks.map((task) => task.id),
}: {
  pathname: string;
  params: Record<string, string>;
  tasks?: { id: string; title: string }[];
  channelTaskIds?: string[];
}) {
  usePathname.mockReturnValue(pathname);
  useParams.mockReturnValue(params);
  useTasks.mockReturnValue({ data: tasks });
  useChannelTasks.mockReturnValue({
    tasks: channelTaskIds.map((taskId) => ({ taskId })),
    isLoading: false,
  });
  useHeaderStore.setState({ content: <span>crumb</span> });
  render(
    <Theme>
      <WebsiteLayout />
    </Theme>,
  );
}

describe("WebsiteLayout task header actions", () => {
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
