import { applyRenameToSummaries } from "@posthog/core/tasks/taskRename";
import type {
  SignalReport,
  SignalReportArtefactsResponse,
  SuggestedReviewer,
  SuggestedReviewersArtefact,
} from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { act, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockSetReviewers = vi.hoisted(() => vi.fn());
const mockClient = vi.hoisted(() => ({
  setSignalReportReviewers: mockSetReviewers,
  getTask: vi.fn(),
  getTaskSummaries: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

vi.mock("@posthog/di/react", async () => {
  const { ReportImplementationService } = await import(
    "@posthog/core/inbox/reportImplementationService"
  );
  const service = new ReportImplementationService();
  return { useService: () => service };
});

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));

import { taskKeys } from "../../tasks/taskKeys";
import { inboxStoryReport } from "../components/inboxStoryFixtures";
import { reportKeys, useUpdateSuggestedReviewers } from "./useInboxReports";
import {
  reportImplementationStatesQueryRoot,
  useReportImplementationStates,
} from "./useReportImplementationStates";

const REPORT_ID = "report-1";
const ARTEFACT_ID = "art-1";

function reviewer(login: string, uuid?: string): SuggestedReviewer {
  return {
    github_login: login,
    github_name: login,
    relevant_commits: [],
    user: uuid
      ? {
          id: 1,
          uuid,
          email: `${login}@x.io`,
          first_name: login,
          last_name: "",
        }
      : null,
  };
}

function artefact(content: SuggestedReviewer[]): SuggestedReviewersArtefact {
  return {
    id: ARTEFACT_ID,
    type: "suggested_reviewers",
    created_at: "2024-01-01T00:00:00Z",
    content,
  };
}

function renderUpdateHook() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const result = renderHook(() => useUpdateSuggestedReviewers(REPORT_ID), {
    wrapper,
  });
  return { ...result, queryClient };
}

describe("Inbox report queries", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("optimistically appends a new latest reviewers row, keeping the prior one", async () => {
    mockSetReviewers.mockResolvedValue(artefact([reviewer("octocat")]));
    const { result, queryClient } = renderUpdateHook();

    const key = reportKeys.artefacts(REPORT_ID);
    queryClient.setQueryData<SignalReportArtefactsResponse>(key, {
      results: [artefact([reviewer("octocat"), reviewer("hubot")])],
      count: 1,
    });

    const next = [reviewer("octocat")];
    await act(async () => {
      await result.current.mutateAsync({
        content: [{ github_login: "octocat" }],
        optimisticReviewers: next,
      });
    });

    expect(mockSetReviewers).toHaveBeenCalledWith(REPORT_ID, [
      { github_login: "octocat" },
    ]);

    const cached = queryClient.getQueryData<SignalReportArtefactsResponse>(key);
    const reviewerRows = (cached?.results ?? []).filter(
      (a): a is SuggestedReviewersArtefact => a.type === "suggested_reviewers",
    );
    // The prior row is preserved untouched as history.
    const priorRow = reviewerRows.find((a) => a.id === ARTEFACT_ID);
    expect(priorRow?.content.map((r) => r.github_login)).toEqual([
      "octocat",
      "hubot",
    ]);
    // A new synthetic row is appended and is the latest (current reviewers).
    const latest = reviewerRows.reduce((a, b) =>
      a.created_at > b.created_at ? a : b,
    );
    expect(latest.id).not.toBe(ARTEFACT_ID);
    expect(latest.content.map((r) => r.github_login)).toEqual(["octocat"]);
  });

  it("invalidates report lists after updating reviewers", async () => {
    mockSetReviewers.mockResolvedValue(artefact([reviewer("octocat")]));
    const { result, queryClient } = renderUpdateHook();

    const listKey = reportKeys.list({ suggested_reviewers: "user-me" });
    queryClient.setQueryData(listKey, { results: [], count: 0 });

    await act(async () => {
      await result.current.mutateAsync({
        content: [{ github_login: "octocat" }],
        optimisticReviewers: [reviewer("octocat")],
      });
    });

    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true);
  });

  it("rolls back the cache when the request fails", async () => {
    const failure = new Error("boom");
    mockSetReviewers.mockRejectedValue(failure);
    const { result, queryClient } = renderUpdateHook();

    const key = reportKeys.artefacts(REPORT_ID);
    const original = [reviewer("octocat"), reviewer("hubot")];
    queryClient.setQueryData<SignalReportArtefactsResponse>(key, {
      results: [artefact(original)],
      count: 1,
    });

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.mutateAsync({
          content: [{ github_login: "octocat" }],
          optimisticReviewers: [reviewer("octocat")],
        });
      } catch (error) {
        caught = error;
      }
    });
    expect(caught).toBe(failure);

    const cached = queryClient.getQueryData<SignalReportArtefactsResponse>(key);
    const cachedArtefact = cached?.results.find((a) => a.id === ARTEFACT_ID) as
      | SuggestedReviewersArtefact
      | undefined;
    expect(cachedArtefact?.content.map((r) => r.github_login)).toEqual([
      "octocat",
      "hubot",
    ]);
  });
  it("restores implementation state from the server and returns failed work to triage", async () => {
    const report = inboxStoryReport({
      assignee: { kind: "task", task_id: "implementation-1" },
      work_state: "working",
    });
    mockClient.getTaskSummaries.mockResolvedValue([
      {
        id: "implementation-1",
        latest_run: { status: "in_progress" },
      },
    ]);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(
      () => useReportImplementationStates([report]),
      { wrapper },
    );
    await waitFor(() =>
      expect(result.current.states.get(report.id)).toBe("working"),
    );
    unmount();
    client.clear();
    const reloaded = renderHook(() => useReportImplementationStates([report]), {
      wrapper,
    });
    await waitFor(() =>
      expect(reloaded.result.current.states.get(report.id)).toBe("working"),
    );
    expect(mockClient.getTaskSummaries).toHaveBeenCalledTimes(2);
    expect(mockClient.getTask).not.toHaveBeenCalled();
    mockClient.getTaskSummaries.mockResolvedValue([
      {
        id: "implementation-1",
        latest_run: { status: "failed" },
      },
    ]);
    await act(async () => {
      await client.invalidateQueries({
        queryKey: reportImplementationStatesQueryRoot,
      });
    });
    await waitFor(() =>
      expect(reloaded.result.current.states.get(report.id)).toBe("failed"),
    );
    mockClient.getTaskSummaries.mockRejectedValue(
      new Error("Status unavailable"),
    );
    await act(async () => {
      await client.invalidateQueries({
        queryKey: reportImplementationStatesQueryRoot,
      });
    });
    await waitFor(() =>
      expect(reloaded.result.current.states.get(report.id)).toBe("unknown"),
    );
    reloaded.unmount();
    client.clear();
  });
  it("scopes the implementation-state query so signing out clears it", async () => {
    const report = inboxStoryReport({
      assignee: { kind: "task", task_id: "implementation-2" },
      work_state: "working",
    });
    mockClient.getTaskSummaries.mockResolvedValue([
      {
        id: "implementation-2",
        latest_run: { status: "in_progress" },
      },
    ]);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(
      () => useReportImplementationStates([report]),
      { wrapper },
    );
    await waitFor(() =>
      expect(result.current.states.get(report.id)).toBe("working"),
    );
    unmount();

    const cached = client
      .getQueryCache()
      .findAll({ queryKey: reportImplementationStatesQueryRoot });
    expect(cached).toHaveLength(1);
    expect(cached[0].meta).toEqual({ authScoped: true });

    client.removeQueries({
      predicate: (query) => query.meta?.authScoped === true,
    });
    expect(
      client
        .getQueryCache()
        .findAll({ queryKey: reportImplementationStatesQueryRoot }),
    ).toHaveLength(0);
  });
  it("keeps the state map out of reach of task-summary writers", async () => {
    const report = inboxStoryReport({
      assignee: { kind: "task", task_id: "implementation-3" },
      work_state: "working",
    });
    mockClient.getTaskSummaries.mockResolvedValue([
      {
        id: "implementation-3",
        latest_run: { status: "in_progress" },
      },
    ]);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(
      () => useReportImplementationStates([report]),
      { wrapper },
    );
    await waitFor(() =>
      expect(result.current.states.get(report.id)).toBe("working"),
    );

    // The rename flow renames a task inside every cached TaskSummaryDTO[].
    expect(() =>
      client.setQueriesData<{ id: string; title: string }[]>(
        { queryKey: taskKeys.allSummaries() },
        (old) => applyRenameToSummaries(old, "implementation-3", "Renamed"),
      ),
    ).not.toThrow();
    expect(result.current.states.get(report.id)).toBe("working");
    unmount();
  });
  it("keeps checked task states while another report joins the query", async () => {
    const failed = inboxStoryReport({
      id: "report-failed",
      assignee: { kind: "task", task_id: "implementation-failed" },
      work_state: "working",
    });
    const started = inboxStoryReport({
      id: "report-started",
      assignee: { kind: "task", task_id: "implementation-started" },
      work_state: "working",
    });
    mockClient.getTaskSummaries.mockResolvedValue([
      { id: "implementation-failed", latest_run: { status: "failed" } },
    ]);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender, unmount } = renderHook(
      ({ reports }: { reports: SignalReport[] }) =>
        useReportImplementationStates(reports),
      { wrapper, initialProps: { reports: [failed] } },
    );
    await waitFor(() =>
      expect(result.current.states.get(failed.id)).toBe("failed"),
    );

    // Create PR puts a task on the second report, which rekeys the query.
    let release = (): void => {};
    mockClient.getTaskSummaries.mockReturnValue(
      new Promise((resolve) => {
        release = () =>
          resolve([
            { id: "implementation-failed", latest_run: { status: "failed" } },
            {
              id: "implementation-started",
              latest_run: { status: "in_progress" },
            },
          ]);
      }),
    );
    rerender({ reports: [failed, started] });

    expect(result.current.states.get(failed.id)).toBe("failed");
    expect(result.current.states.get(started.id)).toBe("checking");

    await act(async () => release());
    await waitFor(() =>
      expect(result.current.states.get(started.id)).toBe("working"),
    );
    expect(result.current.states.get(failed.id)).toBe("failed");
    unmount();
    client.clear();
  });
});
