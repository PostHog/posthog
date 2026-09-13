import { ApiRequestError } from "@posthog/api-client/fetcher";
import type {
  SignalReportArtefactsResponse,
  Task,
  TaskRun,
  TaskRunArtefact,
  TaskRunStatus,
} from "@posthog/shared/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getSignalReportArtefacts: vi.fn(),
  getTask: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

import { reportKeys } from "./useInboxReports";
import {
  derivePurpose,
  fetchReportTasks,
  findContinuableImplementationTask,
  findLatestDiscussionTask,
  findPendingStartedTaskId,
  getTaskPrUrl,
  type ReportTaskData,
  type ReportTaskPurpose,
  useReportTasks,
} from "./useReportTasks";

function makeTask(
  id: string,
  run?: {
    status?: TaskRunStatus;
    prUrl?: string | null;
    prMerged?: boolean;
    prState?: string;
  },
): Task {
  let output: Record<string, unknown> | null = null;
  if (run?.prUrl) {
    output = { pr_url: run.prUrl };
    if (run.prMerged) output.pr_merged = true;
    if (run.prState) output.pr_state = run.prState;
  }
  const latest_run: TaskRun | undefined = run
    ? {
        id: `${id}-run`,
        task: id,
        team: 1,
        branch: null,
        status: run.status ?? "in_progress",
        log_url: "",
        error_message: null,
        output,
        state: {},
        created_at: "2026-06-24T10:00:00Z",
        updated_at: "2026-06-24T10:00:00Z",
        completed_at: null,
      }
    : undefined;
  return {
    id,
    task_number: null,
    slug: id,
    title: id,
    description: "",
    created_at: "2026-06-24T10:00:00Z",
    updated_at: "2026-06-24T10:00:00Z",
    origin_product: "signals",
    latest_run,
  };
}

function entry(
  task: Task,
  purpose: ReportTaskPurpose = "implementation",
): ReportTaskData {
  return { task, purpose, purposeLabel: purpose, startedAt: task.created_at };
}

function taskRunArtefact(taskId: string, type: string): TaskRunArtefact {
  return {
    id: `artefact-${taskId}`,
    type: "task_run",
    content: { task_id: taskId, product: "signals", type },
    created_at: "2026-06-24T10:00:00Z",
  };
}

function artefactsResponse(
  artefacts: TaskRunArtefact[],
): SignalReportArtefactsResponse {
  return { results: artefacts, count: artefacts.length };
}

describe("fetchReportTasks", () => {
  function client(getTask: (taskId: string) => Promise<Task>) {
    return { getTask: (taskId: string) => getTask(taskId) };
  }

  it("keeps the surviving runs when a task_run artefact points at a deleted task", async () => {
    const implementation = makeTask("impl", { prUrl: "https://gh/pr/1" });
    const tasks = await fetchReportTasks(
      client(async (taskId) => {
        if (taskId === "scout") {
          throw new ApiRequestError(404, '{"detail":"Not found."}');
        }
        return implementation;
      }),
      [
        taskRunArtefact("scout", "scout"),
        taskRunArtefact("impl", "implementation"),
      ],
    );

    expect(tasks.map((t) => t.task)).toEqual([implementation]);
  });

  it("fails the fetch when a task lookup errors for any other reason", async () => {
    await expect(
      fetchReportTasks(
        client(async () => {
          throw new ApiRequestError(500, '{"detail":"Server error."}');
        }),
        [taskRunArtefact("impl", "implementation")],
      ),
    ).rejects.toThrow(ApiRequestError);
  });
});

describe("useReportTasks", () => {
  const REPORT_ID = "report-1";
  const artefacts = artefactsResponse([
    taskRunArtefact("impl", "implementation"),
  ]);

  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.getSignalReportArtefacts.mockResolvedValue(artefacts);
    mockClient.getTask.mockImplementation(async (taskId: string) =>
      makeTask(taskId),
    );
  });

  function newQueryClient() {
    return new QueryClient({ defaultOptions: { queries: { retry: false } } });
  }

  function renderReportTasks(queryClient: QueryClient) {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return renderHook(() => useReportTasks(REPORT_ID, "ready"), { wrapper });
  }

  it("fills the shared artefacts cache with the whole log", async () => {
    const queryClient = newQueryClient();
    const { result } = renderReportTasks(queryClient);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.map((t) => t.task.id)).toEqual(["impl"]);
    // The whole log, not the default page: the scout run is written when the
    // report is created, so it is the first row a default page drops.
    expect(mockClient.getSignalReportArtefacts).toHaveBeenCalledWith(
      REPORT_ID,
      { limit: 1000 },
    );
    expect(queryClient.getQueryData(reportKeys.artefacts(REPORT_ID))).toEqual(
      artefacts,
    );
  });

  it("reads a fresh shared artefacts cache instead of fetching again", async () => {
    const queryClient = newQueryClient();
    queryClient.setQueryData(reportKeys.artefacts(REPORT_ID), artefacts);
    const { result } = renderReportTasks(queryClient);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.map((t) => t.task.id)).toEqual(["impl"]);
    expect(mockClient.getSignalReportArtefacts).not.toHaveBeenCalled();
  });
});

describe("derivePurpose", () => {
  it.each([
    ["research", "Research"],
    ["implementation", "Implementation"],
    ["discussion", "Discussion"],
    ["scout", "Scout"],
    ["a_future_run_type", "A future run type"],
  ])("keeps the signals %s run in the list", (type, purposeLabel) => {
    expect(derivePurpose({ product: "signals", type })?.purposeLabel).toBe(
      purposeLabel,
    );
  });

  it("drops repo selection plumbing", () => {
    expect(
      derivePurpose({ product: "signals", type: "repo_selection" }),
    ).toBeNull();
  });

  it("labels a custom agent run with its product and type", () => {
    expect(derivePurpose({ product: "my_agent", type: "sweep" })).toEqual({
      purpose: "other",
      purposeLabel: "My agent — Sweep",
    });
  });
});

describe("findContinuableImplementationTask", () => {
  it("returns null when there are no report tasks", () => {
    expect(findContinuableImplementationTask(undefined)).toBeNull();
    expect(findContinuableImplementationTask([])).toBeNull();
  });

  it("ignores research/other tasks", () => {
    const tasks = [
      entry(makeTask("r", { status: "in_progress" }), "research"),
      entry(makeTask("o", { prUrl: "https://gh/pr/1" }), "other"),
    ];
    expect(findContinuableImplementationTask(tasks)).toBeNull();
  });

  it("returns an implementation task that already has a PR", () => {
    const withPr = makeTask("impl", {
      status: "completed",
      prUrl: "https://gh/pr/9",
    });
    expect(findContinuableImplementationTask([entry(withPr)])).toBe(withPr);
  });

  it("returns a still-running implementation task with no PR yet", () => {
    const running = makeTask("impl", { status: "in_progress" });
    expect(findContinuableImplementationTask([entry(running)])).toBe(running);
  });

  it.each<TaskRunStatus>(["completed", "failed", "cancelled"])(
    "treats a terminal %s run with no PR as not continuable",
    (status) => {
      const terminal = makeTask("impl", { status });
      expect(findContinuableImplementationTask([entry(terminal)])).toBeNull();
    },
  );

  it("prefers a task with a PR over a merely-running one", () => {
    const running = makeTask("running", { status: "in_progress" });
    const withPr = makeTask("withPr", {
      status: "completed",
      prUrl: "https://gh/pr/9",
    });
    // Order shouldn't matter — the PR task wins either way.
    expect(
      findContinuableImplementationTask([entry(running), entry(withPr)]),
    ).toBe(withPr);
    expect(
      findContinuableImplementationTask([entry(withPr), entry(running)]),
    ).toBe(withPr);
  });

  it("ignores a failed run that produced no PR even when one is running", () => {
    const failed = makeTask("failed", { status: "failed" });
    const running = makeTask("running", { status: "queued" });
    expect(
      findContinuableImplementationTask([entry(failed), entry(running)]),
    ).toBe(running);
  });

  it("treats a merged PR as history, not continuable work", () => {
    const merged = makeTask("merged", {
      status: "completed",
      prUrl: "https://gh/pr/9",
      prMerged: true,
    });
    expect(findContinuableImplementationTask([entry(merged)])).toBeNull();
  });

  it("continues a still-open PR and skips a merged one", () => {
    const merged = makeTask("merged", {
      status: "completed",
      prUrl: "https://gh/pr/1",
      prMerged: true,
    });
    const open = makeTask("open", {
      status: "completed",
      prUrl: "https://gh/pr/2",
    });
    expect(
      findContinuableImplementationTask([entry(merged), entry(open)]),
    ).toBe(open);
  });
});

describe("findPendingStartedTaskId", () => {
  it("bridges a started task until it appears in the report tasks", () => {
    expect(findPendingStartedTaskId(undefined, "started")).toBe("started");
    expect(findPendingStartedTaskId([], "started")).toBe("started");
    expect(
      findPendingStartedTaskId([entry(makeTask("started"))], "started"),
    ).toBeNull();
  });

  it("returns null when there is no started task", () => {
    expect(findPendingStartedTaskId([], null)).toBeNull();
  });
});

describe("findLatestDiscussionTask", () => {
  it("returns the newest discussion and ignores other purposes", () => {
    const older = entry(makeTask("old-chat"), "discussion");
    older.startedAt = "2026-06-20T10:00:00Z";
    const newer = entry(makeTask("new-chat"), "discussion");
    newer.startedAt = "2026-06-24T10:00:00Z";
    const impl = entry(makeTask("impl", { prUrl: "https://gh/pr/1" }));
    expect(findLatestDiscussionTask([impl, older, newer])).toBe(newer.task);
    expect(findLatestDiscussionTask([impl])).toBeNull();
    expect(findLatestDiscussionTask(undefined)).toBeNull();
  });
});

describe("getTaskPrUrl", () => {
  it("returns the PR url when present", () => {
    expect(
      getTaskPrUrl(makeTask("t", { status: "completed", prUrl: "https://x" })),
    ).toBe("https://x");
  });

  it("returns null when there is no run or no PR", () => {
    expect(getTaskPrUrl(makeTask("t"))).toBeNull();
    expect(getTaskPrUrl(makeTask("t", { status: "in_progress" }))).toBeNull();
  });
});
