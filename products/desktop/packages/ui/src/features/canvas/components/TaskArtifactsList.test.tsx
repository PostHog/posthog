import type { Task, TaskRun, TaskRunArtifact } from "@posthog/shared";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  runs: [] as TaskRun[],
  openArtifactTab: vi.fn(),
  openExternalUrl: vi.fn(),
}));

vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: (url: string) => mocks.openExternalUrl(url),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useTaskRuns", () => ({
  useTaskRuns: () => ({ runs: mocks.runs, isLoading: false }),
}));
vi.mock("@posthog/ui/features/panels/panelLayoutStore", () => ({
  usePanelLayoutStore: () => mocks.openArtifactTab,
}));
vi.mock("@posthog/ui/features/git-interaction/usePrArtifact", () => ({
  usePrArtifact: (url: string) => ({
    safeUrl: url,
    title: `Pull request #${url.split("/").at(-1)}`,
    stateLabel: "Open",
    Icon: () => <span />,
    iconColor: "currentColor",
  }),
}));
vi.mock("@posthog/ui/features/pr-review/usePrComments", () => ({
  usePrComments: () => ({ data: undefined }),
}));
vi.mock("@posthog/ui/features/pr-review/usePrReviewThreads", () => ({
  usePrReviewThreads: () => ({ data: undefined }),
}));
vi.mock("@posthog/ui/features/sessions/components/useComments", () => ({
  useCommentsForTargetsQuery: () => ({
    data: [
      {
        id: "comment-1",
        source_comment: null,
        item_id: "a",
        content: "Tighten this summary",
        created_at: "2024-01-01T00:00:00Z",
        item_context: { anchor: { kind: "document" } },
      },
      {
        id: "reply-1",
        source_comment: "comment-1",
        item_id: "a",
        content: "Agreed",
        created_at: "2024-01-01T00:01:00Z",
        item_context: { anchor: { kind: "document" } },
      },
      {
        id: "comment-2",
        source_comment: null,
        item_id: "a",
        content: "Second thread",
        created_at: "2024-01-01T00:02:00Z",
        item_context: { anchor: { kind: "document" } },
      },
    ],
  }),
}));

import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { TaskArtifactsList } from "./TaskArtifactsList";

const task = {
  id: "task-1",
  latest_run: null,
} as unknown as Task;

function run(
  id: string,
  options: { prNumber?: number; artifacts?: Partial<TaskRunArtifact>[] } = {},
): TaskRun {
  return {
    id,
    output: options.prNumber
      ? { pr_url: `https://github.com/acme/repo/pull/${options.prNumber}` }
      : null,
    artifacts: options.artifacts,
  } as unknown as TaskRun;
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

describe("TaskArtifactsList", () => {
  beforeEach(() => {
    mocks.runs = [run("run-1", { prNumber: 1 }), run("run-2", { prNumber: 2 })];
    mocks.openArtifactTab.mockReset();
    mocks.openExternalUrl.mockReset();
    useReviewNavigationStore.setState({
      reviewModes: {},
      selectedPrUrls: {},
    });
  });

  it("opens the PR represented by the selected historical row", () => {
    render(<TaskArtifactsList task={task} timeline={[]} canOpenInPlace />);

    fireEvent.click(screen.getByText("Pull request #2"));

    const state = useReviewNavigationStore.getState();
    expect(state.selectedPrUrls[task.id]).toBe(
      "https://github.com/acme/repo/pull/2",
    );
    expect(state.reviewModes[task.id]).toBe("split");
    expect(mocks.openExternalUrl).not.toHaveBeenCalled();
  });

  it("opens a PR externally with no review pane alongside to open into", () => {
    render(<TaskArtifactsList task={task} timeline={[]} />);

    fireEvent.click(screen.getByText("Pull request #2"));

    expect(mocks.openExternalUrl).toHaveBeenCalledWith(
      "https://github.com/acme/repo/pull/2",
    );
    expect(useReviewNavigationStore.getState().reviewModes[task.id]).toBe(
      undefined,
    );
  });

  it("lists every PR produced by the same run", () => {
    mocks.runs = [
      {
        ...run("run-1"),
        output: {
          pr_url: "https://github.com/acme/repo/pull/1",
          pr_urls: [
            "https://github.com/acme/repo/pull/1",
            "https://github.com/acme/other-repo/pull/2",
          ],
        },
      } as TaskRun,
    ];

    render(<TaskArtifactsList task={task} timeline={[]} />);

    expect(screen.getByText("Pull request #1")).toBeTruthy();
    expect(screen.getByText("Pull request #2")).toBeTruthy();
  });

  it("lists uploaded files with their comment count", () => {
    mocks.runs = [
      run("run-1", { artifacts: [outputFile({ id: "a", size: 16861 })] }),
    ];

    render(<TaskArtifactsList task={task} timeline={[]} />);

    const row = screen.getByText("report.md").closest("button");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("2")).toBeTruthy();
    expect(within(row as HTMLElement).queryByText(/File|KB/)).toBeNull();
  });

  // The threads themselves live in the Comments tab now, so the pane must not
  // grow a second list of them.
  it("leaves the thread list to the Comments tab", () => {
    mocks.runs = [
      run("run-1", { artifacts: [outputFile({ id: "a", size: 16861 })] }),
    ];

    render(<TaskArtifactsList task={task} timeline={[]} />);

    expect(screen.queryByText("Tighten this summary")).toBeNull();
  });

  // The row should read like the chat's file list: markdown looks like
  // markdown, HTML looks like HTML.
  it.each([
    { name: "notes.md", icon: "markdown" },
    { name: "demo.html", icon: "html" },
  ])("gives $name an icon for its file type", ({ name, icon }) => {
    mocks.runs = [run("run-1", { artifacts: [outputFile({ id: "a", name })] })];

    const { container } = render(
      <TaskArtifactsList task={task} timeline={[]} />,
    );

    expect(container.querySelector("img")?.getAttribute("src")).toContain(icon);
  });

  it("opens the artifact of the run that produced it beside the chat", () => {
    mocks.runs = [
      run("run-1", { artifacts: [outputFile({ id: "a", name: "old.md" })] }),
      run("run-2", {
        artifacts: [
          outputFile({
            id: "b",
            name: "new.md",
            storage_path: "runs/2/new.md",
          }),
        ],
      }),
    ];

    render(<TaskArtifactsList task={task} timeline={[]} />);
    fireEvent.click(screen.getByText("new.md"));

    expect(mocks.openArtifactTab).toHaveBeenCalledWith("task-1", {
      runId: "run-2",
      artifactId: "b",
      name: "new.md",
    });
  });

  // Agents revise a deliverable and upload it again under the same name.
  it("keeps only the newest upload of a repeatedly revised file", () => {
    mocks.runs = [
      run("run-1", {
        artifacts: [
          outputFile({
            id: "a",
            size: 1000,
            uploaded_at: "2026-07-27T08:00:00+00:00",
          }),
          outputFile({
            id: "b",
            size: 2000,
            storage_path: "runs/1/report-v2.md",
            uploaded_at: "2026-07-27T09:00:00+00:00",
          }),
        ],
      }),
    ];

    render(<TaskArtifactsList task={task} timeline={[]} />);

    expect(screen.getAllByText("report.md")).toHaveLength(1);
    expect(screen.queryByText(/File ·|KB/)).toBeNull();
  });

  it.each([
    { name: "a plan", type: "plan" as const },
    { name: "a user attachment", type: "user_attachment" as const },
    { name: "a skill bundle", type: "skill_bundle" as const },
  ])("shows the empty state for a run with only $name", ({ type }) => {
    mocks.runs = [run("run-1", { artifacts: [outputFile({ id: "a", type })] })];

    render(<TaskArtifactsList task={task} timeline={[]} />);

    expect(screen.getByText("No artifacts yet")).toBeTruthy();
  });
});
