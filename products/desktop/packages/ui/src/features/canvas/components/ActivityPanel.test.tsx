import type { Task } from "@posthog/shared/domain-types";
import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  type MockInstance,
  vi,
} from "vitest";

vi.mock("@posthog/ui/features/canvas/hooks/useThreadConversation", () => ({
  useThreadConversation: () => ({
    timeline: [],
    agentStatus: null,
    events: [],
    isPromptPending: false,
    isReady: true,
    members: [],
    currentUser: null,
    isTaskAuthor: true,
    canForward: true,
    draft: "",
    setDraft: vi.fn(),
    isSubmitDisabled: false,
    submit: vi.fn(),
    sendMessageToAgent: vi.fn(),
    deleteMessage: vi.fn(),
    onMentionInsert: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/features/canvas/components/ActivityTimeline", () => ({
  ActivityTimeline: () => <div>timeline body</div>,
}));
vi.mock("@posthog/ui/features/canvas/components/TaskArtifactsList", () => ({
  TaskArtifactsList: () => <div>artifacts body</div>,
}));
vi.mock("@posthog/ui/features/canvas/components/TaskCommentsList", () => ({
  TaskCommentsList: () => <div>comments body</div>,
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelFeedView", () => ({
  TaskCard: () => <div>task card</div>,
}));
vi.mock("@posthog/ui/features/canvas/components/ThreadPanel", () => ({
  AgentStatusLine: () => <div>agent status</div>,
  ThreadLoadingState: () => <div>loading</div>,
  ThreadReplyComposer: () => <div>composer</div>,
}));
vi.mock("@posthog/ui/features/tasks/queries", () => ({
  taskDetailQuery: () => ({ queryKey: ["task"], queryFn: vi.fn() }),
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: undefined }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { ActivityPanel } from "./ActivityPanel";

const task = { id: "task-1", title: "Ship it" } as unknown as Task;

function renderPanel(taskId = "task-1") {
  return render(
    <ActivityPanel
      taskId={taskId}
      channelId="channel-1"
      task={{ ...task, id: taskId }}
      showTaskSummary={false}
    />,
  );
}

describe("ActivityPanel", () => {
  let scrollTo: MockInstance;

  beforeEach(() => {
    scrollTo = vi.spyOn(Element.prototype, "scrollTo");
    useCommentNavigationStore.setState({
      focusByTask: {},
      resolutionsByTarget: {},
    });
  });

  afterEach(() => {
    scrollTo.mockRestore();
  });

  it("offers comments as a third tab beside the timeline and artifacts", () => {
    renderPanel();

    expect(screen.getByRole("tab", { name: "Timeline" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Artifacts" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Comments" }));

    expect(screen.getByText("comments body")).toBeTruthy();
    // The composer belongs to the conversation, not to a list of threads.
    expect(screen.queryByText("composer")).toBeNull();
  });

  // A thread picked on the artifact itself lands in this tab, so the pick has
  // to bring the tab with it.
  it("switches to comments when a thread is picked elsewhere", () => {
    renderPanel();
    expect(screen.getByText("timeline body")).toBeTruthy();

    act(() =>
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(
          "task-1",
          { scope: "task_artifact", itemId: "artifact-1" },
          "comment-1",
        ),
    );

    expect(screen.getByText("comments body")).toBeTruthy();
  });

  it("leaves a focus request for another task alone", () => {
    renderPanel();

    act(() =>
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(
          "task-2",
          { scope: "task_artifact", itemId: "artifact-1" },
          "comment-1",
        ),
    );

    expect(screen.getByText("timeline body")).toBeTruthy();
  });

  // A focus left over from an earlier visit must not hijack the panel, and the
  // panel is reused across tasks without remounting.
  it("does not open comments for a focus that predates the task", () => {
    useCommentNavigationStore
      .getState()
      .requestCommentFocus(
        "task-2",
        { scope: "task_artifact", itemId: "artifact-1" },
        "comment-1",
      );
    const { rerender } = renderPanel("task-1");

    rerender(
      <ActivityPanel
        taskId="task-2"
        channelId="channel-1"
        task={{ ...task, id: "task-2" }}
        showTaskSummary={false}
      />,
    );

    expect(screen.getByText("timeline body")).toBeTruthy();
  });

  // Only the timeline reads bottom-up; the thread lists put what matters on top.
  it("keeps the comments list where it was scrolled to", () => {
    renderPanel();
    expect(scrollTo).toHaveBeenCalled();
    const timelineScrolls = scrollTo.mock.calls.length;

    fireEvent.click(screen.getByRole("tab", { name: "Comments" }));

    expect(scrollTo.mock.calls.length).toBe(timelineScrolls);
  });
});
