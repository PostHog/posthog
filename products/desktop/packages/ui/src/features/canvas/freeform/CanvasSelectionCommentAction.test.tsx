import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasSelectionCommentAction } from "./CanvasSelectionCommentAction";

const { mutateAsync } = vi.hoisted(() => ({ mutateAsync: vi.fn() }));

vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({ members: [] }),
}));
vi.mock("@posthog/ui/features/sessions/components/useComments", () => ({
  useCreateComment: () => ({ mutateAsync }),
}));
vi.mock(
  "@posthog/ui/features/code-editor/components/SelectionCommentOverlay",
  () => ({
    SelectionCommentOverlay: ({
      open,
      onSubmit,
    }: {
      open: boolean;
      onSubmit: (
        start: number,
        end: number,
        content: string,
        mentions: number[],
      ) => void;
    }) =>
      open ? (
        <button
          type="button"
          onClick={() => onSubmit(0, 0, "Please revise this", [4])}
        >
          Submit selection comment
        </button>
      ) : null,
  }),
);

describe("CanvasSelectionCommentAction", () => {
  beforeEach(() => {
    mutateAsync.mockReset();
    useCanvasChatPanelStore.setState({ collapsed: true, tab: "chat" });
    useCommentNavigationStore.setState({
      focusByTask: {},
      resolutionsByTarget: {},
    });
  });

  it("creates the text-anchored comment and opens the comments tab", async () => {
    mutateAsync.mockResolvedValue({ id: "comment-1" });
    render(
      <CanvasSelectionCommentAction
        selection={{
          quote: "selected text",
          prefix: "before ",
          suffix: " after",
          start: 7,
          end: 20,
          rect: { top: 10, right: 80, bottom: 30, left: 20 },
        }}
        taskId="task-1"
        dashboardId="canvas-1"
        canvasName="Launch canvas"
        versionId="version-2"
        onDismiss={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("Submit selection comment"));

    expect(useCanvasChatPanelStore.getState()).toMatchObject({
      collapsed: false,
      tab: "comments",
    });
    expect(mutateAsync).toHaveBeenCalledWith({
      content: "Please revise this",
      context: {
        anchor: {
          kind: "text",
          quote: "selected text",
          prefix: "before ",
          suffix: " after",
          start: 7,
          end: 20,
        },
        canvasVersionId: "version-2",
      },
      mentions: [4],
    });
    await waitFor(() =>
      expect(
        useCommentNavigationStore.getState().focusByTask["task-1"],
      ).toMatchObject({
        threadId: "comment-1",
        intent: "focus-only",
      }),
    );
  });
});
