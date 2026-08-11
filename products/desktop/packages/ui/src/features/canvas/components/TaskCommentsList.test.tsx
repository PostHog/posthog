import type { ResourceComment } from "@posthog/api-client/posthog-client";
import type { ThreadTimelineRow } from "@posthog/core/canvas/threadTimeline";
import type { Task, TaskRun, TaskRunArtifact } from "@posthog/shared";
import type { TaskThreadMessage } from "@posthog/shared/domain-types";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  runs: [] as TaskRun[],
  comments: [] as unknown[],
  activeArtifactId: null as string | null,
  prConversation: [] as unknown[],
  prReviewThreads: [] as unknown[],
  openArtifactTab: vi.fn(),
  openPrInReview: vi.fn(),
  openExternalUrl: vi.fn(),
  requestScrollToFile: vi.fn(),
  prReply: vi.fn(async () => true),
  prResolve: vi.fn(async () => true),
  createComment: vi.fn(),
  setResolved: vi.fn(),
  createdFor: [] as unknown[],
  resolvedFor: [] as unknown[],
  queriedTargets: [] as unknown[],
  prCommentUrls: [] as string[],
  prReviewUrls: [] as string[],
  prTitleUrls: [] as string[],
  prQueriesLoading: false,
}));

function openThread(body: string): void {
  const card = screen.getByText(body).closest("[data-comment-thread-id]");
  expect(card).not.toBeNull();
  fireEvent.click(
    within(card as HTMLElement).getByRole("button", {
      name: "Open comment thread",
    }),
  );
}

vi.mock("@posthog/ui/features/canvas/hooks/useTaskRuns", () => ({
  useTaskRuns: () => ({ runs: mocks.runs, isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({ members: [] }),
}));
vi.mock("@posthog/ui/features/panels/panelLayoutStore", () => ({
  usePanelLayoutStore: () => mocks.openArtifactTab,
  useActiveArtifactId: () => mocks.activeArtifactId,
}));
vi.mock("@posthog/ui/features/pr-review/usePrCommentsForUrls", () => ({
  usePrCommentsForUrls: (urls: string[]) => {
    mocks.prCommentUrls = urls;
    return {
      byUrl: new Map(urls.map((url) => [url, mocks.prConversation])),
      isLoading: mocks.prQueriesLoading,
    };
  },
}));
vi.mock("@posthog/ui/features/pr-review/usePrReviewThreadsForUrls", () => ({
  usePrReviewThreadsForUrls: (urls: string[]) => {
    mocks.prReviewUrls = urls;
    return {
      byUrl: new Map(urls.map((url) => [url, mocks.prReviewThreads])),
      isLoading: mocks.prQueriesLoading,
    };
  },
}));
vi.mock("@posthog/ui/features/git-interaction/usePrDetails", () => ({
  usePrTitles: (urls: string[]) => {
    mocks.prTitleUrls = urls;
    return {};
  },
}));
vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: (url: string) => mocks.openExternalUrl(url),
}));
// GitHub bodies render through MarkdownRenderer; the wiring under test is the
// list, not the markdown pipeline, so keep it to plain text here.
vi.mock("@posthog/ui/features/editor/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <span>{content}</span>
  ),
}));
vi.mock("@posthog/ui/features/code-review/openPrInReview", () => ({
  openPrInReview: (taskId: string, url: string) =>
    mocks.openPrInReview(taskId, url),
}));
vi.mock("@posthog/ui/features/code-review/reviewNavigationStore", () => ({
  useReviewNavigationStore: {
    getState: () => ({ requestScrollToFile: mocks.requestScrollToFile }),
  },
}));
// Tiptap's editor renders no placeholder attribute and drags a lot of DOM into
// jsdom; the wiring under test is which target a composed comment posts to.
vi.mock("@posthog/ui/features/sessions/components/CommentComposer", () => ({
  CommentComposer: ({
    placeholder,
    onSubmit,
  }: {
    placeholder: string;
    onSubmit: (content: string, mentions: number[]) => void;
  }) => (
    <button type="button" onClick={() => onSubmit("Composed comment", [])}>
      {placeholder}
    </button>
  ),
}));
vi.mock("@posthog/ui/features/code-review/hooks/usePrCommentActions", () => ({
  usePrCommentActions: () => ({
    reply: mocks.prReply,
    resolve: mocks.prResolve,
  }),
}));
vi.mock("@posthog/ui/features/sessions/components/useComments", () => ({
  isOptimisticComment: (comment: ResourceComment) =>
    comment.id.startsWith("optimistic-"),
  useCommentsQuery: (target: unknown) => {
    if (target) mocks.queriedTargets.push([target]);
    return {
      data: mocks.comments,
      isLoading: false,
    };
  },
  useCommentsForTargetsQuery: (targets: unknown) => {
    if (Array.isArray(targets) && targets.length > 0) {
      mocks.queriedTargets.push(targets);
    }
    return {
      data: mocks.comments,
      isLoading: false,
    };
  },
  useCreateComment: (target: unknown) => {
    mocks.createdFor.push(target);
    return { mutateAsync: mocks.createComment, isPending: false };
  },
  useSetCommentResolved: (target: unknown) => {
    mocks.resolvedFor.push(target);
    return { mutate: mocks.setResolved, isPending: false };
  },
}));

import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { TaskCommentsList } from "./TaskCommentsList";

const task = { id: "task-1", latest_run: null } as unknown as Task;

function run(artifacts: Partial<TaskRunArtifact>[], id = "run-1"): TaskRun {
  return { id, output: null, artifacts } as unknown as TaskRun;
}

function outputFile(
  overrides: Partial<TaskRunArtifact>,
): Partial<TaskRunArtifact> {
  return {
    type: "output",
    name: "report.md",
    storage_path: "runs/1/report.md",
    ...overrides,
  };
}

function prRun(url: string): TaskRun {
  return {
    id: "run-pr",
    output: { pr_url: url },
    artifacts: [],
  } as unknown as TaskRun;
}

function reviewThread(overrides: Record<string, unknown> = {}) {
  return {
    nodeId: "node-1",
    isResolved: false,
    rootId: 501,
    filePath: "packages/ui/src/App.tsx",
    comments: [
      {
        id: 501,
        body: "This needs a guard",
        path: "packages/ui/src/App.tsx",
        line: 12,
        user: { login: "octocat", avatar_url: "" },
        created_at: "2024-01-02T00:00:00Z",
      },
    ],
    ...overrides,
  };
}

function comment(overrides: Partial<ResourceComment>): ResourceComment {
  return {
    id: "comment-1",
    created_by: null,
    content: "Tighten this summary",
    created_at: "2024-01-01T00:00:00Z",
    item_id: "a",
    item_context: { anchor: { kind: "document" } },
    scope: "task_artifact",
    source_comment: null,
    ...overrides,
  } as ResourceComment;
}

describe("TaskCommentsList", () => {
  beforeEach(() => {
    mocks.runs = [
      run([
        outputFile({ id: "a", name: "report.md" }),
        outputFile({
          id: "b",
          name: "summary.md",
          storage_path: "runs/1/summary.md",
        }),
      ]),
    ];
    mocks.comments = [
      comment({}),
      comment({
        id: "reply-1",
        source_comment: "comment-1",
        content: "Agreed",
        created_at: "2024-01-01T00:01:00Z",
      }),
      comment({
        id: "comment-2",
        item_id: "b",
        content: "Second thread",
        created_at: "2024-01-01T00:02:00Z",
      }),
    ];
    mocks.activeArtifactId = null;
    mocks.prConversation = [];
    mocks.prReviewThreads = [];
    mocks.openArtifactTab.mockReset();
    mocks.openPrInReview.mockReset();
    mocks.openExternalUrl.mockReset();
    mocks.requestScrollToFile.mockReset();
    mocks.prReply.mockClear();
    mocks.prResolve.mockClear();
    mocks.createComment.mockReset();
    mocks.createComment.mockResolvedValue({ id: "created-comment" });
    mocks.setResolved.mockReset();
    mocks.createdFor = [];
    mocks.resolvedFor = [];
    mocks.queriedTargets = [];
    mocks.prCommentUrls = [];
    mocks.prReviewUrls = [];
    mocks.prTitleUrls = [];
    mocks.prQueriesLoading = false;
    useCommentNavigationStore.setState({
      focusByTask: {},
      resolutionsByTarget: {},
    });
  });

  it("limits GitHub comment queries to 20 pull requests", () => {
    mocks.runs = Array.from({ length: 25 }, (_, index) =>
      prRun(`https://github.com/acme/repo/pull/${index + 1}`),
    );

    render(<TaskCommentsList task={task} timeline={[]} />);

    const expectedUrls = Array.from(
      { length: 20 },
      (_, index) => `https://github.com/acme/repo/pull/${index + 1}`,
    );
    expect(mocks.prCommentUrls).toEqual(expectedUrls);
    expect(mocks.prReviewUrls).toEqual(expectedUrls);
    expect(mocks.prTitleUrls).toEqual(expectedUrls);
  });

  it("queries and displays only the current canvas when restricted", async () => {
    const onCanvasCommentOpen = vi.fn();
    mocks.comments = [
      comment({
        item_id: "canvas-1",
        scope: "desktop_canvas",
        content: "Canvas feedback",
        item_context: {
          anchor: {
            kind: "text",
            quote: "important copy",
            prefix: "",
            suffix: "",
            start: 0,
            end: 14,
          },
          canvasVersionId: "version-2",
        },
      }),
    ];

    render(
      <TaskCommentsList
        task={task}
        timeline={[]}
        onlySource={{
          kind: "canvas",
          name: "Launch canvas",
          target: { scope: "desktop_canvas", itemId: "canvas-1" },
          url: null,
        }}
        canvasVersionId="version-2"
        commentVersionLabel={() => "V2"}
        onCanvasCommentOpen={onCanvasCommentOpen}
      />,
    );

    expect(mocks.queriedTargets.at(-1)).toEqual([
      { scope: "desktop_canvas", itemId: "canvas-1" },
    ]);
    expect(screen.getByText("Canvas feedback")).toBeInTheDocument();
    expect(screen.getByText("“important copy”")).toBeInTheDocument();
    expect(screen.getByText("V2 ·")).toBeInTheDocument();
    expect(screen.queryByText("Selected text")).not.toBeInTheDocument();
    expect(screen.queryByText("Whole canvas")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Filter by source")).not.toBeInTheDocument();
    expect(screen.queryByText("Launch canvas")).not.toBeInTheDocument();
    expect(mocks.createdFor.at(-1)).toEqual({
      scope: "desktop_canvas",
      itemId: "canvas-1",
    });

    openThread("Canvas feedback");
    expect(onCanvasCommentOpen).toHaveBeenCalledWith("version-2");

    await act(async () => {
      fireEvent.click(screen.getByText(/Comment on this canvas/));
    });
    expect(mocks.createComment).toHaveBeenCalledWith({
      content: "Composed comment",
      context: {
        anchor: { kind: "document" },
        canvasVersionId: "version-2",
      },
      mentions: [],
    });
  });

  it("shows selected artifact text alongside its source", () => {
    mocks.comments = [
      comment({
        item_context: {
          anchor: {
            kind: "text",
            quote: "Purpose",
            prefix: "",
            suffix: "",
            start: 0,
            end: 7,
          },
        },
      }),
    ];

    render(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByText("report.md")).toBeTruthy();
    expect(screen.getByText("“Purpose”")).toBeTruthy();
  });

  it("loads canvas comments from a local-development artifact link", () => {
    mocks.runs = [];
    mocks.comments = [
      comment({
        item_id: "canvas-1",
        scope: "desktop_canvas",
        content: "Linked canvas feedback",
      }),
    ];

    const timeline = [
      {
        kind: "artifact",
        timestamp: 1,
        message: { id: "message-1" },
        artifact: {
          kind: "canvas",
          name: "Dev Joke Machine",
          url: "http://localhost:8000/code/canvas/channel-1/canvas-1",
        },
      },
    ] as unknown as ThreadTimelineRow<TaskThreadMessage>[];

    render(<TaskCommentsList task={task} timeline={timeline} />);

    expect(mocks.queriedTargets.at(-1)).toContainEqual({
      scope: "desktop_canvas",
      itemId: "canvas-1",
    });
    expect(screen.getByText("Linked canvas feedback")).toBeInTheDocument();
  });

  // The tab is the one place to see every thread the task produced, so each row
  // has to say which artifact it came from.
  it("lists open threads from every artifact, newest first", () => {
    render(<TaskCommentsList task={task} timeline={[]} />);

    const newest = screen.getByText("Second thread");
    const oldest = screen.getByText("Tighten this summary");
    expect(
      newest.compareDocumentPosition(oldest) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText("summary.md")).toBeTruthy();
    expect(screen.getByText("report.md")).toBeTruthy();
    expect(screen.getByText(/1 reply/)).toBeTruthy();
    // The resolve/reopen reply is thread state, not a comment of its own.
    expect(screen.queryByText("Agreed")).toBeTruthy();
  });

  it("opens the artifact a thread belongs to and focuses that thread", () => {
    render(<TaskCommentsList task={task} timeline={[]} />);

    openThread("Tighten this summary");

    expect(mocks.openArtifactTab).toHaveBeenCalledWith("task-1", {
      runId: "run-1",
      artifactId: "a",
      name: "report.md",
    });
    expect(useCommentNavigationStore.getState().focusByTask["task-1"]).toEqual({
      target: { scope: "task_artifact", itemId: "a" },
      threadId: "comment-1",
      nonce: expect.any(Number),
      openCommentsTab: true,
      intent: "navigate",
    });
  });

  it("opens an artifact when activity requests its comment thread", () => {
    render(<TaskCommentsList task={task} timeline={[]} />);

    act(() => {
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(
          "task-1",
          { scope: "task_artifact", itemId: "a" },
          "comment-1",
        );
    });

    expect(mocks.openArtifactTab).toHaveBeenCalledWith("task-1", {
      runId: "run-1",
      artifactId: "a",
      name: "report.md",
    });
  });

  it("scrolls the comment pane without reopening the selected artifact", () => {
    const animationFrame = vi
      .spyOn(globalThis, "requestAnimationFrame")
      .mockImplementation((callback) => {
        callback(0);
        return 0;
      });
    render(<TaskCommentsList task={task} timeline={[]} />);
    const thread = screen
      .getByText("Tighten this summary")
      .closest("[data-comment-thread-id]") as HTMLElement;
    const pane = thread.parentElement as HTMLElement;
    Object.defineProperty(pane, "scrollTop", { value: 20, writable: true });
    pane.getBoundingClientRect = () => ({ top: 0, bottom: 100 }) as DOMRect;
    thread.getBoundingClientRect = () => ({ top: 120, bottom: 160 }) as DOMRect;
    const paneScroll = vi.spyOn(pane, "scrollTo");
    const outerScroll = vi.spyOn(Element.prototype, "scrollIntoView");

    act(() => {
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(
          "task-1",
          { scope: "task_artifact", itemId: "a" },
          "comment-1",
          { intent: "reveal-thread" },
        );
    });

    expect(paneScroll).toHaveBeenCalledWith({
      top: 80,
      behavior: "smooth",
    });
    expect(outerScroll).not.toHaveBeenCalled();
    expect(mocks.openArtifactTab).not.toHaveBeenCalled();
    paneScroll.mockRestore();
    outerScroll.mockRestore();
    animationFrame.mockRestore();
  });

  it("opens the saved canvas version when activity requests its thread", () => {
    const onCanvasCommentOpen = vi.fn();
    mocks.comments = [
      comment({
        item_id: "canvas-1",
        scope: "desktop_canvas",
        content: "Historical canvas feedback",
        item_context: {
          anchor: { kind: "document" },
          canvasVersionId: "version-2",
        },
      }),
    ];

    render(
      <TaskCommentsList
        task={task}
        timeline={[]}
        onlySource={{
          kind: "canvas",
          name: "Launch canvas",
          target: { scope: "desktop_canvas", itemId: "canvas-1" },
          url: null,
        }}
        canvasVersionId="version-3"
        onCanvasCommentOpen={onCanvasCommentOpen}
      />,
    );

    act(() => {
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(
          "task-1",
          { scope: "desktop_canvas", itemId: "canvas-1" },
          "comment-1",
        );
    });

    expect(onCanvasCommentOpen).toHaveBeenCalledWith("version-2");
  });

  // Clicking the same thread twice has to scroll twice, so every request is a
  // new nonce rather than a no-op set.
  it("re-requests focus for a thread already focused", () => {
    render(<TaskCommentsList task={task} timeline={[]} />);

    openThread("Tighten this summary");
    const first = useCommentNavigationStore.getState().focusByTask["task-1"];
    openThread("Tighten this summary");
    const second = useCommentNavigationStore.getState().focusByTask["task-1"];

    expect(second?.nonce).toBeGreaterThan(first?.nonce ?? 0);
  });

  it("filters between open and resolved threads", () => {
    mocks.comments = [
      comment({}),
      comment({
        id: "state-1",
        source_comment: "comment-1",
        content: "Resolved this thread",
        created_at: "2024-01-01T00:03:00Z",
        item_context: {
          anchor: { kind: "document" },
          threadState: "resolved",
        },
      }),
      comment({
        id: "comment-2",
        item_id: "b",
        content: "Second thread",
        created_at: "2024-01-01T00:02:00Z",
      }),
    ];

    render(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByText("Second thread")).toBeTruthy();
    expect(screen.queryByText("Tighten this summary")).toBeNull();

    fireEvent.click(screen.getByLabelText("Filter comments"));
    fireEvent.click(screen.getByText("Resolved (1)"));

    expect(screen.getByText("Tighten this summary")).toBeTruthy();
    expect(screen.queryByText("Second thread")).toBeNull();
  });

  it("warns when the anchored text the thread points at has changed", () => {
    useCommentNavigationStore.setState({
      resolutionsByTarget: {
        "task_artifact:a": new Map([["comment-1", "orphaned" as const]]),
      },
    });

    render(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByText("The highlighted text changed")).toBeTruthy();
  });

  it("replies and resolves against the thread's own resource", () => {
    render(<TaskCommentsList task={task} timeline={[]} />);

    // Each row builds its mutations from its own target, since the list spans
    // several resources.
    expect(mocks.createdFor).toContainEqual({
      scope: "task_artifact",
      itemId: "a",
    });
    expect(mocks.resolvedFor).toContainEqual({
      scope: "task_artifact",
      itemId: "b",
    });

    const thread = screen
      .getByText("Tighten this summary")
      .closest("[data-comment-thread-id]") as HTMLElement;
    fireEvent.click(within(thread).getByText("Resolve"));

    expect(mocks.setResolved).toHaveBeenCalledWith({
      root: expect.objectContaining({ id: "comment-1" }),
      resolved: true,
    });
  });

  // The pane follows what's on screen, but a reader who picks a source owns the
  // filter from then on.
  it("narrows to the artifact open in the main pane", () => {
    mocks.activeArtifactId = "b";

    render(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByText("Second thread")).toBeTruthy();
    expect(screen.queryByText("Tighten this summary")).toBeNull();
  });

  it("labels an active artifact that has no comments", () => {
    mocks.runs = [
      run([
        outputFile({ id: "a", name: "report.md" }),
        outputFile({
          id: "empty",
          name: "empty.md",
          storage_path: "runs/1/empty.md",
        }),
      ]),
    ];
    mocks.comments = [comment({})];
    mocks.activeArtifactId = "empty";

    render(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByLabelText("Filter by source")).toHaveTextContent(
      "empty.md",
    );
    expect(screen.queryByText("Tighten this summary")).toBeNull();
    fireEvent.click(screen.getByLabelText("Filter by source"));
    const emptySourceOption = screen
      .getAllByText("empty.md")
      .at(-1)
      ?.closest('[role="menuitemradio"]');
    expect(emptySourceOption).toHaveTextContent("0");
  });

  it("follows an active artifact once its run data arrives", () => {
    mocks.runs = [];
    mocks.activeArtifactId = "late";
    const { rerender } = render(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByLabelText("Filter by source")).toHaveTextContent(
      "All sources",
    );

    mocks.runs = [
      run([
        outputFile({
          id: "late",
          name: "late.md",
          storage_path: "runs/1/late.md",
        }),
      ]),
    ];
    rerender(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByLabelText("Filter by source")).toHaveTextContent(
      "late.md",
    );
  });

  it("resumes following the main pane after All sources is selected", () => {
    mocks.activeArtifactId = "b";
    const { rerender } = render(<TaskCommentsList task={task} timeline={[]} />);

    fireEvent.click(screen.getByLabelText("Filter by source"));
    fireEvent.click(screen.getByText(/^All sources/));
    mocks.activeArtifactId = "a";
    rerender(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.queryByText("Second thread")).toBeNull();
    expect(screen.getByText("Tighten this summary")).toBeTruthy();
  });

  it("stops following the main pane while a specific source is selected", () => {
    mocks.activeArtifactId = null;
    const { rerender } = render(<TaskCommentsList task={task} timeline={[]} />);

    fireEvent.click(screen.getByLabelText("Filter by source"));
    fireEvent.click(screen.getAllByText("report.md").at(-1) as HTMLElement);
    mocks.activeArtifactId = "b";
    rerender(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.queryByText("Second thread")).toBeNull();
    expect(screen.getByText("Tighten this summary")).toBeTruthy();
  });

  it("lists a PR's review threads and conversation comments", () => {
    mocks.runs = [prRun("https://github.com/acme/repo/pull/7")];
    mocks.comments = [];
    mocks.prReviewThreads = [reviewThread()];
    mocks.prConversation = [
      {
        id: 900,
        author: "octocat",
        avatarUrl: null,
        body: "Shipping this",
        createdAt: "2024-01-03T00:00:00Z",
        url: "https://github.com/acme/repo/pull/7#issuecomment-900",
      },
    ];

    render(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByText("This needs a guard")).toBeTruthy();
    expect(screen.getByText("Shipping this")).toBeTruthy();
    expect(screen.getAllByText("PR #7").length).toBe(2);
    // Only the file-anchored thread can be resolved on GitHub.
    expect(screen.getAllByText("Resolve")).toHaveLength(1);
    // The conversation comment can't be handled here, so it links out instead.
    expect(screen.getByText("View on GitHub")).toBeTruthy();
  });

  it("links a conversation comment out to GitHub", () => {
    mocks.runs = [prRun("https://github.com/acme/repo/pull/7")];
    mocks.comments = [];
    mocks.prConversation = [
      {
        id: 900,
        author: "octocat",
        avatarUrl: null,
        body: "Shipping this",
        createdAt: "2024-01-03T00:00:00Z",
        url: "https://github.com/acme/repo/pull/7#issuecomment-900",
      },
    ];

    render(<TaskCommentsList task={task} timeline={[]} />);
    fireEvent.click(screen.getByText("View on GitHub"));

    expect(mocks.openExternalUrl).toHaveBeenCalledWith(
      "https://github.com/acme/repo/pull/7#issuecomment-900",
    );
  });

  it("opens a PR thread in the review pane at its file", () => {
    mocks.runs = [prRun("https://github.com/acme/repo/pull/7")];
    mocks.comments = [];
    mocks.prReviewThreads = [reviewThread()];

    render(<TaskCommentsList task={task} timeline={[]} />);
    openThread("This needs a guard");

    expect(mocks.openPrInReview).toHaveBeenCalledWith(
      "task-1",
      "https://github.com/acme/repo/pull/7",
    );
    expect(mocks.requestScrollToFile).toHaveBeenCalledWith(
      "task-1",
      "packages/ui/src/App.tsx",
    );
  });

  it("replies and resolves a PR thread on GitHub", () => {
    mocks.runs = [prRun("https://github.com/acme/repo/pull/7")];
    mocks.comments = [];
    mocks.prReviewThreads = [reviewThread()];

    render(<TaskCommentsList task={task} timeline={[]} />);
    const thread = screen
      .getByText("This needs a guard")
      .closest("[data-comment-thread-id]") as HTMLElement;
    fireEvent.click(within(thread).getByText("Resolve"));

    expect(mocks.prResolve).toHaveBeenCalledWith("node-1", true);
    expect(mocks.setResolved).not.toHaveBeenCalled();
  });

  // Not every comment belongs to a deliverable; some are about the work.
  it("posts a comment on the task itself without scrolling", async () => {
    render(<TaskCommentsList task={task} timeline={[]} />);

    await act(async () => {
      fireEvent.click(screen.getByText(/Comment on this task/));
    });

    expect(mocks.createdFor).toContainEqual({
      scope: "task",
      itemId: "task-1",
    });
    expect(mocks.createComment).toHaveBeenCalledWith(
      expect.objectContaining({
        content: "Composed comment",
        context: { anchor: { kind: "document" } },
      }),
    );
    expect(
      useCommentNavigationStore.getState().focusByTask["task-1"],
    ).toMatchObject({
      target: { scope: "task", itemId: "task-1" },
      threadId: "created-comment",
      intent: "focus-only",
    });
  });

  it("polls at most 20 artifact comment targets plus the task", () => {
    mocks.runs = [
      run(
        Array.from({ length: 25 }, (_, index) =>
          outputFile({
            id: `artifact-${index}`,
            name: `artifact-${index}.md`,
            storage_path: `runs/1/artifact-${index}.md`,
          }),
        ),
      ),
    ];

    render(<TaskCommentsList task={task} timeline={[]} />);

    const queriedTargets = mocks.queriedTargets.at(-1) as Array<{
      scope: string;
      itemId: string;
    }>;
    expect(queriedTargets).toHaveLength(21);
    expect(queriedTargets[0]).toEqual({
      scope: "task",
      itemId: "task-1",
    });
  });

  it("loads GitHub comments for at most four PRs at once", () => {
    mocks.prQueriesLoading = true;
    mocks.runs = Array.from({ length: 8 }, (_, index) =>
      prRun(`https://github.com/acme/repo/pull/${index + 1}`),
    );

    render(<TaskCommentsList task={task} timeline={[]} />);

    expect(mocks.prCommentUrls).toHaveLength(4);
    expect(mocks.prReviewUrls).toHaveLength(4);
    expect(mocks.prTitleUrls).toHaveLength(4);
  });

  it("shows an empty state pointing at the artifact surfaces", () => {
    mocks.comments = [];

    render(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByText("No open comments")).toBeTruthy();
  });
});
