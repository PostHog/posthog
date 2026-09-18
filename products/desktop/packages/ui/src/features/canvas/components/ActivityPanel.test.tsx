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

// Mutable so a test can render the panel mid-load. Hoisted because a plain `let`
// is initialized after the hoisted mock factories.
const loaded = vi.hoisted(() => ({ thread: true }));

vi.mock("@posthog/ui/features/canvas/hooks/useThreadConversation", () => ({
  useThreadConversation: () => ({
    timeline: [],
    hasLoadedThread: loaded.thread,
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
// The panel warms this from the task id before the task itself arrives, so it is mounted
// even in the tests that never get a task.
vi.mock("@posthog/ui/features/canvas/hooks/useTaskThread", () => ({
  useTaskThread: () => ({ messages: [], isLoading: false, hasLoaded: true }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskRuns", () => ({
  useTaskRuns: () => ({ runs: [], isLoading: false, refreshRuns: vi.fn() }),
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
  TaskSummaryRow: () => <div>task summary</div>,
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
    loaded.thread = true;
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

  // A request nobody has shown yet is outstanding whenever it was written, and
  // the click that picks a thread often precedes the surface that can show it.
  it.each([
    { name: "before the panel rendered the task", beforeMount: true },
    { name: "while the panel was on another task", beforeMount: false },
  ])("opens comments for a request made $name", ({ beforeMount }) => {
    const request = () =>
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(
          "task-2",
          { scope: "task_artifact", itemId: "artifact-1" },
          "comment-1",
        );

    if (beforeMount) request();
    const { rerender } = renderPanel("task-1");
    if (!beforeMount) act(request);

    rerender(
      <ActivityPanel
        taskId="task-2"
        channelId="channel-1"
        task={{ ...task, id: "task-2" }}
        showTaskSummary={false}
      />,
    );

    expect(screen.getByText("comments body")).toBeTruthy();
    // Acknowledged on the way, so the request is spent rather than reopening
    // comments over every later surface that reads it.
    expect(
      useCommentNavigationStore.getState().focusByTask["task-2"]
        ?.openCommentsTab,
    ).toBe(false);
  });

  // Only the timeline reads bottom-up; the thread lists put what matters on top.
  it("keeps the comments list where it was scrolled to", () => {
    renderPanel();
    expect(scrollTo).toHaveBeenCalled();
    const timelineScrolls = scrollTo.mock.calls.length;

    fireEvent.click(screen.getByRole("tab", { name: "Comments" }));

    expect(scrollTo.mock.calls.length).toBe(timelineScrolls);
  });

  it("waits for the thread, then never takes the timeline away again", () => {
    // The loader belongs to the first paint only, never over rows already on screen.
    loaded.thread = false;
    // A fresh element each time: React bails out of `rerender` when handed the identical one.
    const panel = () => (
      <ActivityPanel
        taskId="task-1"
        channelId="channel-1"
        task={task}
        showTaskSummary={false}
      />
    );
    const view = render(panel());
    expect(screen.getByLabelText("Loading timeline")).toBeInTheDocument();

    loaded.thread = true;
    view.rerender(panel());
    expect(screen.getByText("timeline body")).toBeInTheDocument();

    // A refetch flips a query back to loading; the rows must stay put.
    loaded.thread = false;
    view.rerender(panel());
    expect(screen.getByText("timeline body")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading timeline")).toBeNull();
  });
});
