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
  TaskCommentsList: ({ task }: { task: { id: string } }) => (
    <div data-testid="task-comments">{task.id}</div>
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

describe("CanvasSidePanel", () => {
  beforeEach(() => {
    useCanvasChatPanelStore.setState({ tab: "chat", collapsed: false });
  });

  it("switches from the canvas task chat to all task comments", () => {
    render(
      <CanvasSidePanel
        effectiveTaskId="task-1"
        commentTaskId="task-1"
        onMinimize={vi.fn()}
        dashboardId="canvas-1"
        channelId="channel-1"
        channelName="General"
        name="Launch canvas"
      />,
    );

    expect(screen.getByTestId("task-chat")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Comments"));
    expect(screen.getByTestId("task-comments")).toHaveTextContent("task-1");
  });
});
