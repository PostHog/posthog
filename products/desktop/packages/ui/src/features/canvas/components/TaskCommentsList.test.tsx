import type { ResourceComment } from "@posthog/api-client/posthog-client";
import type { Task, TaskRun, TaskRunArtifact } from "@posthog/shared";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
}));

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
  usePrCommentsForUrls: (urls: string[]) => ({
    byUrl: new Map(urls.map((url) => [url, mocks.prConversation])),
    isLoading: false,
  }),
}));
vi.mock("@posthog/ui/features/pr-review/usePrReviewThreadsForUrls", () => ({
  usePrReviewThreadsForUrls: (urls: string[]) => ({
    byUrl: new Map(urls.map((url) => [url, mocks.prReviewThreads])),
    isLoading: false,
  }),
}));
vi.mock("@posthog/ui/features/git-interaction/usePrDetails", () => ({
  usePrTitles: () => ({}),
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
  useCommentsForTargetsQuery: () => ({
    data: mocks.comments,
    isLoading: false,
  }),
  useCreateComment: (target: unknown) => {
    mocks.createdFor.push(target);
    return { mutate: mocks.createComment, isPending: false };
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
    mocks.setResolved.mockReset();
    mocks.createdFor = [];
    mocks.resolvedFor = [];
    useCommentNavigationStore.setState({
      focusByTask: {},
      resolutionsByTarget: {},
    });
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

    fireEvent.click(screen.getByText("Tighten this summary"));

    expect(mocks.openArtifactTab).toHaveBeenCalledWith("task-1", {
      runId: "run-1",
      artifactId: "a",
      name: "report.md",
    });
    expect(useCommentNavigationStore.getState().focusByTask["task-1"]).toEqual({
      target: { scope: "task_artifact", itemId: "a" },
      threadId: "comment-1",
      nonce: expect.any(Number),
    });
  });

  // Clicking the same thread twice has to scroll twice, so every request is a
  // new nonce rather than a no-op set.
  it("re-requests focus for a thread already focused", () => {
    render(<TaskCommentsList task={task} timeline={[]} />);

    fireEvent.click(screen.getByText("Tighten this summary"));
    const first = useCommentNavigationStore.getState().focusByTask["task-1"];
    fireEvent.click(screen.getByText("Tighten this summary"));
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

  it("stops following the main pane once a source is picked by hand", () => {
    mocks.activeArtifactId = "b";
    const { rerender } = render(<TaskCommentsList task={task} timeline={[]} />);

    fireEvent.click(screen.getByLabelText("Filter by source"));
    fireEvent.click(screen.getByText(/^All sources/));
    mocks.activeArtifactId = "a";
    rerender(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByText("Second thread")).toBeTruthy();
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
    fireEvent.click(screen.getByText("This needs a guard"));

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
  it("posts a comment on the task itself", () => {
    render(<TaskCommentsList task={task} timeline={[]} />);

    fireEvent.click(screen.getByText(/Comment on this task/));

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
  });

  it("shows an empty state pointing at the artifact surfaces", () => {
    mocks.comments = [];

    render(<TaskCommentsList task={task} timeline={[]} />);

    expect(screen.getByText("No open comments")).toBeTruthy();
  });
});
