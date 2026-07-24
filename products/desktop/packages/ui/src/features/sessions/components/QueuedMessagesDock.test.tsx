import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const queuedState = vi.hoisted(() => ({
  messages: [] as Array<{ id: string; content: string; queuedAt: number }>,
}));

const sessionState = vi.hoisted(() => ({
  editingQueuedId: undefined as string | undefined,
}));

const sessionService = vi.hoisted(() => ({
  steerQueuedMessage: vi.fn().mockResolvedValue(undefined),
  clearEditingQueuedMessage: vi.fn(),
}));

const storeSetters = vi.hoisted(() => ({
  removeQueuedMessage: vi.fn(),
  moveQueuedMessage: vi.fn(),
}));

const dndCapture = vi.hoisted(() => ({
  onDragOver: undefined as ((event: unknown) => void) | undefined,
}));

vi.mock("@posthog/core/sessions/sessionService", () => ({
  SESSION_SERVICE: Symbol.for("test.session-service"),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => sessionService,
}));

vi.mock("@posthog/ui/features/sessions/useSession", () => ({
  useQueuedMessagesForTask: () => queuedState.messages,
}));

vi.mock("@posthog/ui/features/sessions/hooks/useMessagingMode", () => ({
  useSupportsNativeSteer: () => false,
}));

vi.mock("@posthog/ui/features/sessions/hooks/useEditQueuedMessage", () => ({
  useEditQueuedMessage: () => vi.fn(),
  useCancelQueuedMessageEdit: () => vi.fn(),
}));

vi.mock("@posthog/ui/features/sessions/sessionStore", () => ({
  sessionStoreSetters: storeSetters,
  useSessionIsCloud: () => false,
  useSessionSelector: <T,>(
    _taskId: string,
    select: (session: { editingQueuedId?: string }) => T,
  ) => select({ editingQueuedId: sessionState.editingQueuedId }),
  useSessionStore: {
    getState: () => ({
      taskIdIndex: new Proxy({}, { get: () => "run-1" }) as Record<
        string,
        string
      >,
      sessions: { "run-1": { messageQueue: queuedState.messages } },
    }),
  },
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));

// The dock's reorder handler is driven directly through the captured
// onDragOver prop; the sortable plumbing itself is @dnd-kit's to test.
vi.mock("@dnd-kit/react", async () => {
  const React = await import("react");
  return {
    DragDropProvider: ({
      onDragOver,
      children,
    }: {
      onDragOver: (event: unknown) => void;
      children: React.ReactNode;
    }) => {
      dndCapture.onDragOver = onDragOver;
      return React.createElement(React.Fragment, null, children);
    },
  };
});
vi.mock("@dnd-kit/react/sortable", () => ({
  useSortable: () => ({
    ref: () => {},
    handleRef: () => {},
    isDragging: false,
  }),
}));
vi.mock("@dnd-kit/dom", () => ({ PointerSensor: class {} }));

// Stub the per-message card so the test exercises the dock's collapse/scroll
// shell, not the markdown/steer internals it already owns.
vi.mock(
  "@posthog/ui/features/sessions/components/session-update/QueuedMessageView",
  async () => {
    const React = await import("react");
    return {
      QueuedMessageView: ({
        message,
        isEditing,
      }: {
        message: { content: string };
        isEditing?: boolean;
      }) =>
        React.createElement(
          "div",
          {
            "data-testid": "queued-card",
            "data-editing": String(!!isEditing),
          },
          message.content,
        ),
    };
  },
);

import { QueuedMessagesDock } from "./QueuedMessagesDock";

const TWO_MESSAGES = [
  { id: "q1", content: "first queued message", queuedAt: 1 },
  { id: "q2", content: "second queued message", queuedAt: 2 },
];

// Each test uses a distinct taskId so the (real, per-task) collapse state in
// sessionViewStore never bleeds between cases.
function renderDock(taskId: string) {
  return render(
    <Theme>
      <QueuedMessagesDock taskId={taskId} />
    </Theme>,
  );
}

describe("QueuedMessagesDock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queuedState.messages = [];
    sessionState.editingQueuedId = undefined;
    dndCapture.onDragOver = undefined;
  });

  it("renders nothing when the queue is empty", () => {
    queuedState.messages = [];
    const { container } = render(<QueuedMessagesDock taskId="task-empty" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is expanded by default and shows every queued message with a count", () => {
    queuedState.messages = TWO_MESSAGES;
    renderDock("task-expanded");

    expect(screen.getByText("first queued message")).toBeInTheDocument();
    expect(screen.getByText("second queued message")).toBeInTheDocument();
    expect(screen.getByText("2 queued")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Collapse queued messages" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("caps the list height and scrolls so it can't push the composer down", () => {
    queuedState.messages = TWO_MESSAGES;
    const { container } = renderDock("task-scroll");

    const scroller = container.querySelector(".overflow-y-auto");
    expect(scroller).not.toBeNull();
    expect(scroller?.classList.contains("max-h-[30vh]")).toBe(true);
  });

  it("collapses and expands the list when the header is toggled", () => {
    queuedState.messages = TWO_MESSAGES;
    renderDock("task-toggle");

    expect(screen.getAllByTestId("queued-card")).toHaveLength(2);

    fireEvent.click(
      screen.getByRole("button", { name: "Collapse queued messages" }),
    );

    // Collapsed: cards are hidden, but the header with the live count stays.
    expect(screen.queryAllByTestId("queued-card")).toHaveLength(0);
    expect(screen.getByText("2 queued")).toBeInTheDocument();
    const trigger = screen.getByRole("button", {
      name: "Expand queued messages",
    });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    expect(screen.getAllByTestId("queued-card")).toHaveLength(2);
  });

  it("reorders the queue when a card is dragged over another", () => {
    queuedState.messages = TWO_MESSAGES;
    renderDock("task-drag");

    dndCapture.onDragOver?.({
      operation: { source: { id: "q1" }, target: { id: "q2" } },
    });

    expect(storeSetters.moveQueuedMessage).toHaveBeenCalledWith(
      "task-drag",
      0,
      1,
    );
  });

  it.each([
    {
      name: "source and target are the same card",
      operation: { source: { id: "q1" }, target: { id: "q1" } },
    },
    {
      name: "source is not in the queue",
      operation: { source: { id: "missing" }, target: { id: "q2" } },
    },
    {
      name: "target is not in the queue",
      operation: { source: { id: "q1" }, target: { id: "missing" } },
    },
    {
      name: "there is no drop target",
      operation: { source: { id: "q1" }, target: undefined },
    },
  ])("does not reorder when $name", ({ operation }) => {
    queuedState.messages = TWO_MESSAGES;
    renderDock("task-drag-noop");

    dndCapture.onDragOver?.({ operation });

    expect(storeSetters.moveQueuedMessage).not.toHaveBeenCalled();
  });

  it("marks only the edited message's card as editing", () => {
    queuedState.messages = TWO_MESSAGES;
    sessionState.editingQueuedId = "q1";
    renderDock("task-editing");

    const [first, second] = screen.getAllByTestId("queued-card");
    expect(first).toHaveAttribute("data-editing", "true");
    expect(second).toHaveAttribute("data-editing", "false");
    expect(sessionService.clearEditingQueuedMessage).not.toHaveBeenCalled();
  });

  it("clears a stale edit hold when the edited message leaves the queue", () => {
    queuedState.messages = TWO_MESSAGES;
    sessionState.editingQueuedId = "q-gone";
    renderDock("task-stale-hold");

    expect(sessionService.clearEditingQueuedMessage).toHaveBeenCalledWith(
      "task-stale-hold",
    );
  });
});
