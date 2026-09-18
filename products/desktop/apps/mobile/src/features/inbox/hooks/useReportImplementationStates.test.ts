import type { SignalReport } from "@posthog/shared/domain-types";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/auth", () => ({
  useAuthStore: () => ({ projectId: 1, oauthAccessToken: "token" }),
}));
vi.mock("@/lib/posthogApiClient", () => ({
  getPostHogApiClient: () => ({}),
}));

import {
  collectTaskIds,
  deriveStates,
  loadImplementationTasks,
} from "./useReportImplementationStates";

function report(overrides: Partial<SignalReport>): SignalReport {
  return { status: "ready", ...overrides } as SignalReport;
}

function taskReport(id: string, taskId: string): SignalReport {
  return report({ id, assignee: { kind: "task", task_id: taskId } });
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("collectTaskIds", () => {
  it("deduplicates task ids and drops reports without one", () => {
    expect(
      collectTaskIds([
        taskReport("a", "t1"),
        taskReport("b", "t2"),
        taskReport("c", "t1"),
        report({ id: "d" }),
      ]),
    ).toEqual(["t1", "t2"]);
  });

  it("returns a stable order so refetches don't churn the query key", () => {
    const first = collectTaskIds([
      taskReport("a", "t2"),
      taskReport("b", "t1"),
    ]);
    const second = collectTaskIds([
      taskReport("b", "t1"),
      taskReport("a", "t2"),
    ]);
    expect(first).toEqual(second);
  });
});

describe("loadImplementationTasks", () => {
  it("batches a single summaries request for every task on screen", async () => {
    const client = {
      getTaskSummaries: vi.fn().mockResolvedValue([
        {
          id: "t1",
          updated_at: "2026-01-01",
          latest_run: { id: "r1", status: "in_progress" },
        },
        {
          id: "t2",
          updated_at: "2026-01-01",
          latest_run: { id: "r2", status: "failed" },
        },
      ]),
      getTask: vi.fn(),
    };
    const tasks = await loadImplementationTasks(
      client as never,
      ["t1", "t2"],
      new Map(),
    );
    expect(client.getTaskSummaries).toHaveBeenCalledTimes(1);
    expect(client.getTaskSummaries).toHaveBeenCalledWith(["t1", "t2"]);
    expect(client.getTask).not.toHaveBeenCalled();
    expect(tasks.get("t1")?.latest_run?.status).toBe("in_progress");
    expect(tasks.get("t2")?.latest_run?.status).toBe("failed");
  });

  it("falls back to getTask for a completed summary that omits pr fields", async () => {
    const client = {
      getTaskSummaries: vi.fn().mockResolvedValue([
        {
          id: "t1",
          updated_at: "2026-01-01",
          latest_run: { id: "r1", status: "completed" },
        },
      ]),
      getTask: vi.fn().mockResolvedValue({
        latest_run: {
          status: "completed",
          output: { pr_url: "https://github.com/x/y/pull/1", pr_state: "open" },
        },
      }),
    };
    const tasks = await loadImplementationTasks(
      client as never,
      ["t1"],
      new Map(),
    );
    expect(client.getTask).toHaveBeenCalledWith("t1");
    expect(tasks.get("t1")?.latest_run?.output).toEqual({
      pr_url: "https://github.com/x/y/pull/1",
      pr_state: "open",
    });
  });

  it("reuses a cached detail promise across calls for the same task version", async () => {
    const client = {
      getTaskSummaries: vi.fn().mockResolvedValue([
        {
          id: "t1",
          updated_at: "2026-01-01",
          latest_run: { id: "r1", status: "completed" },
        },
      ]),
      getTask: vi.fn().mockResolvedValue({
        latest_run: {
          status: "completed",
          output: { pr_url: "https://github.com/x/y/pull/1", pr_state: "open" },
        },
      }),
    };
    const cache = new Map();
    await loadImplementationTasks(client as never, ["t1"], cache);
    await loadImplementationTasks(client as never, ["t1"], cache);
    expect(client.getTask).toHaveBeenCalledTimes(1);
  });

  it("skips the network entirely when no task ids are on screen", async () => {
    const client = {
      getTaskSummaries: vi.fn(),
      getTask: vi.fn(),
    };
    const tasks = await loadImplementationTasks(client as never, [], new Map());
    expect(client.getTaskSummaries).not.toHaveBeenCalled();
    expect(tasks.size).toBe(0);
  });

  it("evicts cached tasks that are no longer on screen", async () => {
    const client = {
      getTaskSummaries: vi.fn().mockResolvedValue([]),
      getTask: vi.fn(),
    };
    const cache = new Map([
      [
        "t1",
        {
          version: "v1",
          expiresAt: Date.now() + 60_000,
          task: Promise.resolve(undefined),
        },
      ],
    ]);
    await loadImplementationTasks(client as never, ["t2"], cache);
    expect(cache.has("t1")).toBe(false);
  });
});

describe("deriveStates", () => {
  it("returns checking for a report whose task has never been loaded", () => {
    const states = deriveStates([taskReport("a", "t1")], undefined, false);
    expect(states.get("a")).toBe("checking");
  });

  it("returns unknown for a report whose task id is missing from a successful load", () => {
    const states = deriveStates([taskReport("a", "t1")], new Map(), true);
    expect(states.get("a")).toBe("unknown");
  });

  it("derives the expected state per loaded task", () => {
    const states = deriveStates(
      [taskReport("a", "t1"), taskReport("b", "t2"), report({ id: "c" })],
      new Map([
        ["t1", { latest_run: { status: "in_progress" } }],
        ["t2", { latest_run: { status: "failed" } }],
      ]),
      true,
    );
    expect(states.get("a")).toBe("working");
    expect(states.get("b")).toBe("failed");
    expect(states.get("c")).toBeNull();
  });
});
