import type { Task } from "@posthog/shared/domain-types";
import type { SignalReport } from "@posthog/shared/types";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasSidePanel } from "./CanvasSidePanel";

vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQuery: () => ({ data: { id: "task-1", title: "Build canvas" } }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useThreadConversation", () => ({
  useThreadConversation: () => ({ timeline: [{ kind: "message" }] }),
}));
vi.mock("@posthog/ui/features/canvas/components/TaskCommentsList", () => ({
  TaskCommentsList: ({
    task,
    onlySource,
  }: {
    task: { id: string };
    onlySource: { target: { itemId: string } };
  }) => (
    <div data-testid="task-comments">
      {task.id}:{onlySource.target.itemId}
    </div>
  ),
}));
vi.mock("@posthog/ui/features/sessions/components/EmbeddedSessionView", () => ({
  EmbeddedSessionView: () => <div data-testid="task-chat" />,
}));
vi.mock("@posthog/ui/features/canvas/freeform/FreeformGenerateBar", () => ({
  FreeformGenerateBar: () => null,
}));
vi.mock("@posthog/ui/features/canvas/freeform/ContextEditor", () => ({
  CanvasContextEditor: () => null,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useDiscussReport", () => ({
  useDiscussReport: () => ({ discussReport: vi.fn(), isDiscussing: false }),
}));

const report = {
  id: "report-1",
  title: "Conversion dropped",
  status: "ready",
} as SignalReport;

describe("CanvasSidePanel", () => {
  beforeEach(() => {
    useCanvasChatPanelStore.setState({ tab: "chat", collapsed: false });
  });

  it("switches from canvas chat to comments for this canvas", () => {
    render(
      <CanvasSidePanel
        effectiveTaskId="task-1"
        commentTaskId="task-1"
        onMinimize={vi.fn()}
        dashboardId="canvas-1"
        channelId="channel-1"
        channelName="General"
        name="Launch canvas"
        displayedVersionId="version-2"
        commentVersionLabel={(versionId) => versionId}
        onCommentOpen={vi.fn()}
      />,
    );

    expect(screen.getByTestId("task-chat")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Comments"));
    expect(screen.getByTestId("task-comments")).toHaveTextContent(
      "task-1:canvas-1",
    );
  });

  it("shows the run that built the canvas on the chat tab while viewing", () => {
    useCanvasChatPanelStore.setState({ tab: "comments", collapsed: false });
    render(
      <CanvasSidePanel
        effectiveTaskId={null}
        commentTaskId="task-1"
        interactive={false}
        onMinimize={vi.fn()}
        dashboardId="canvas-1"
        channelId="channel-1"
        channelName="General"
        name="Launch canvas"
        displayedVersionId="version-2"
        commentVersionLabel={(versionId) => versionId}
        onCommentOpen={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("Chat"));
    expect(screen.getByTestId("task-chat")).toBeInTheDocument();
  });

  it("starts report chat without exposing the canvas builder transcript", () => {
    render(
      <CanvasSidePanel
        effectiveTaskId="builder-task"
        commentTaskId="shared-discussion-task"
        interactive={false}
        onMinimize={vi.fn()}
        dashboardId="canvas-1"
        channelId="channel-1"
        channelName="General"
        name="Conversion dropped"
        displayedVersionId="version-2"
        commentVersionLabel={(versionId) => versionId}
        onCommentOpen={vi.fn()}
        reportId="report-1"
        report={report}
      />,
    );

    expect(screen.getByText("Work from this report")).toBeInTheDocument();
    expect(screen.queryByTestId("task-chat")).not.toBeInTheDocument();
  });

  it("resumes the viewer's report discussion", () => {
    render(
      <CanvasSidePanel
        effectiveTaskId="builder-task"
        commentTaskId="shared-discussion-task"
        interactive={false}
        onMinimize={vi.fn()}
        dashboardId="canvas-1"
        channelId="channel-1"
        channelName="General"
        name="Conversion dropped"
        displayedVersionId="version-2"
        commentVersionLabel={(versionId) => versionId}
        onCommentOpen={vi.fn()}
        reportId="report-1"
        report={report}
        reportDiscussionTask={{ id: "user-discussion-task" } as Task}
      />,
    );

    expect(screen.getByTestId("task-chat")).toBeInTheDocument();
    expect(screen.queryByText("Work from this report")).not.toBeInTheDocument();
  });
});
