import { useTaskSummaries } from "@posthog/ui/features/tasks/useTasks";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  type LoopBuilderSession,
  useLoopBuilderSessionStore,
} from "../loopBuilderSessionStore";
import { useLoopBuilderSessions } from "./useLoopBuilderSessions";

vi.mock("@posthog/ui/shell/rendererStorage", () => ({
  electronStorage: {
    getItem: async () => null,
    setItem: async () => {},
    removeItem: async () => {},
  },
  flushRendererStateWrites: async () => {},
}));
vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTaskSummaries: vi.fn(),
}));
vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => new Set<string>(),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: () => "us:1",
  useAuthStateValue: () => "us:1",
}));

const mockedUseTaskSummaries = vi.mocked(useTaskSummaries);

function session(taskId: string): LoopBuilderSession {
  return {
    taskId,
    prompt: `prompt ${taskId}`,
    startedAt: Date.now(),
    identity: "us:1",
  };
}

function summariesQuery(
  state: "pending" | "placeholder" | "resolved",
  data?: {
    id: string;
    latest_run: { environment: string; status: string } | null;
  }[],
) {
  return {
    data: state === "pending" ? undefined : (data ?? []),
    isSuccess: state !== "pending",
    isPlaceholderData: state === "placeholder",
  } as ReturnType<typeof useTaskSummaries>;
}

beforeEach(() => {
  useLoopBuilderSessionStore.setState({ sessions: [], _hasHydrated: false });
});

describe("useLoopBuilderSessions isSettled", () => {
  it.each([
    {
      name: "unsettled before the store hydrates, even with no sessions",
      hydrated: false,
      sessions: [] as LoopBuilderSession[],
      query: summariesQuery("pending"),
      expected: false,
    },
    {
      name: "settled immediately when hydrated with no sessions",
      hydrated: true,
      sessions: [] as LoopBuilderSession[],
      query: summariesQuery("pending"),
      expected: true,
    },
    {
      name: "unsettled while summaries are pending",
      hydrated: true,
      sessions: [session("a")],
      query: summariesQuery("pending"),
      expected: false,
    },
    {
      name: "unsettled while summaries are placeholder data",
      hydrated: true,
      sessions: [session("a")],
      query: summariesQuery("placeholder"),
      expected: false,
    },
    {
      name: "settled once summaries resolve",
      hydrated: true,
      sessions: [session("a")],
      query: summariesQuery("resolved", [
        {
          id: "a",
          latest_run: { environment: "cloud", status: "in_progress" },
        },
      ]),
      expected: true,
    },
  ])("$name", ({ hydrated, sessions, query, expected }) => {
    useLoopBuilderSessionStore.setState({ sessions, _hasHydrated: hydrated });
    mockedUseTaskSummaries.mockReturnValue(query);
    const { result } = renderHook(() => useLoopBuilderSessions());
    expect(result.current.isSettled).toBe(expected);
  });

  it("keeps unpruned sessions while unsettled", () => {
    useLoopBuilderSessionStore.setState({
      sessions: [session("a")],
      _hasHydrated: true,
    });
    mockedUseTaskSummaries.mockReturnValue(summariesQuery("pending"));
    const { result } = renderHook(() => useLoopBuilderSessions());
    expect(result.current.sessions.map((s) => s.taskId)).toEqual(["a"]);
  });

  it("prunes ended sessions once summaries resolve", () => {
    useLoopBuilderSessionStore.setState({
      sessions: [session("a"), session("b")],
      _hasHydrated: true,
    });
    mockedUseTaskSummaries.mockReturnValue(
      summariesQuery("resolved", [
        { id: "a", latest_run: { environment: "cloud", status: "completed" } },
        {
          id: "b",
          latest_run: { environment: "cloud", status: "in_progress" },
        },
      ]),
    );
    const { result } = renderHook(() => useLoopBuilderSessions());
    expect(result.current.isSettled).toBe(true);
    expect(result.current.sessions.map((s) => s.taskId)).toEqual(["b"]);
  });
});
