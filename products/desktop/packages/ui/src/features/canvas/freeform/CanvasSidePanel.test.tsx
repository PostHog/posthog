import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasSidePanel } from "./CanvasSidePanel";

const mocks = vi.hoisted(() => ({
  task: undefined as { id: string; title: string } | undefined,
}));

vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQuery: () => ({ data: mocks.task }),
}));
vi.mock("@posthog/ui/features/canvas/components/TaskCommentsList", () => ({
  TaskCommentsList: ({
    taskId,
    onlySource,
  }: {
    taskId: string | null;
    onlySource: { target: { itemId: string } };
  }) => (
    <div data-testid="task-comments">
      {taskId}:{onlySource.target.itemId}
    </div>
  ),
}));
vi.mock("@posthog/ui/features/sessions/components/EmbeddedSessionView", () => ({
  EmbeddedSessionView: () => <div data-testid="task-chat" />,
}));
vi.mock("@posthog/ui/features/canvas/freeform/FreeformGenerateBar", () => ({
  FreeformGenerateBar: () => <div data-testid="canvas-composer" />,
}));

describe("CanvasSidePanel", () => {
  beforeEach(() => {
    mocks.task = { id: "task-1", title: "Build canvas" };
    useCanvasChatPanelStore.setState({ tab: "chat", collapsed: false });
  });

  it("switches from canvas chat to comments for this canvas", () => {
    render(
      <CanvasSidePanel
        chatTaskId="task-1"
        commentTaskId="task-1"
        commentsEnabled
        onMinimize={vi.fn()}
        dashboardId="canvas-1"
        channelId="channel-1"
        channelName="General"
        name="Launch canvas"
        displayedVersionId="version-2"
        liveVersionId="version-2"
        onAskAgent={vi.fn()}
        commentVersionLabel={(versionId) => versionId}
        onCommentOpen={vi.fn()}
      />,
    );

    expect(screen.getByTestId("task-chat")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Comments"));
    expect(screen.getByTestId("task-comments")).toHaveTextContent(
      "task-1:canvas-1",
    );
  });

  it.each([true, false])("ends a run with interactive=%s", (interactive) => {
    useCanvasChatPanelStore.setState({ tab: "comments", collapsed: false });
    const props = {
      commentTaskId: "task-1",
      commentsEnabled: true,
      interactive,
      onMinimize: vi.fn(),
      dashboardId: "canvas-1",
      channelId: "channel-1",
      channelName: "General",
      name: "Launch canvas",
      displayedVersionId: "version-2",
      liveVersionId: "version-2",
      onAskAgent: vi.fn(),
      commentVersionLabel: (versionId: string) => versionId,
      onCommentOpen: vi.fn(),
    };
    const { rerender } = render(
      <CanvasSidePanel {...props} chatTaskId="task-1" />,
    );

    fireEvent.click(screen.getByLabelText("Chat"));
    expect(screen.getByTestId("task-chat")).toBeInTheDocument();

    rerender(<CanvasSidePanel {...props} chatTaskId={null} />);
    expect(screen.queryByTestId("task-chat")).not.toBeInTheDocument();
    if (interactive) {
      expect(screen.getByTestId("canvas-composer")).toBeInTheDocument();
    } else {
      expect(screen.getByText("No run yet")).toBeInTheDocument();
    }
  });

  it.each([
    ["the generating run is not readable", "task-1", "task-1:canvas-1"],
    ["no task backs the canvas", null, ":canvas-1"],
  ])("opens comments when %s", (_name, commentTaskId, expected) => {
    mocks.task = undefined;
    useCanvasChatPanelStore.setState({ tab: "comments", collapsed: false });

    render(
      <CanvasSidePanel
        chatTaskId={null}
        commentTaskId={commentTaskId}
        commentsEnabled
        onMinimize={vi.fn()}
        dashboardId="canvas-1"
        channelId="channel-1"
        channelName="General"
        name="Launch canvas"
        displayedVersionId="version-2"
        liveVersionId="version-2"
        onAskAgent={vi.fn()}
        commentVersionLabel={(versionId) => versionId}
        onCommentOpen={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Comments")).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByTestId("task-comments")).toHaveTextContent(expected);
  });

  it("disables comments when they are off for the canvas", () => {
    useCanvasChatPanelStore.setState({ tab: "comments", collapsed: false });

    render(
      <CanvasSidePanel
        chatTaskId="task-1"
        commentTaskId={null}
        commentsEnabled={false}
        onMinimize={vi.fn()}
        dashboardId="canvas-1"
        channelId="channel-1"
        channelName="General"
        name="Launch canvas"
        displayedVersionId="version-2"
        liveVersionId="version-2"
        onAskAgent={vi.fn()}
        commentVersionLabel={(versionId) => versionId}
        onCommentOpen={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Comments")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.queryByTestId("task-comments")).not.toBeInTheDocument();
  });
});
