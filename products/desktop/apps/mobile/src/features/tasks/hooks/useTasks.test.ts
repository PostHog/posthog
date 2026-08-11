import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockUseAuthStore, mockUseUserQuery, mockUseTaskStore } = vi.hoisted(
  () => ({
    mockUseAuthStore: vi.fn(),
    mockUseUserQuery: vi.fn(),
    mockUseTaskStore: vi.fn(),
  }),
);

vi.mock("@/features/auth", () => ({
  useAuthStore: mockUseAuthStore,
  useUserQuery: mockUseUserQuery,
}));

vi.mock("@/lib/logger", () => {
  const mockLogger = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    scope: () => mockLogger,
  };

  return {
    logger: mockLogger,
  };
});

vi.mock("@/lib/posthogApiClient", () => ({
  getPostHogApiClient: vi.fn(() => ({
    createTask: vi.fn(),
    deleteTask: vi.fn(),
    getTask: vi.fn(),
    getTasks: vi.fn(),
    runTaskInCloud: vi.fn(),
    updateTask: vi.fn(),
  })),
}));

vi.mock("../stores/taskStore", () => ({
  filterAndSortTasks: vi.fn((tasks) => tasks),
  useTaskStore: mockUseTaskStore,
}));

import { filterListedTasks, getTaskPollingInterval } from "./useTasks";

const baseTask = {
  id: "task-1",
  task_number: 1,
  slug: "task-1",
  title: "Task 1",
  description: "Do something",
  created_at: "2026-05-13T00:00:00Z",
  updated_at: "2026-05-13T00:00:00Z",
  origin_product: "user_created",
};

describe("useTasks", () => {
  beforeEach(() => {
    mockUseAuthStore.mockReset();
    mockUseUserQuery.mockReset();
    mockUseTaskStore.mockReset();
  });

  it("only polls task queries while a run is still active", () => {
    expect(getTaskPollingInterval(undefined)).toBe(false);
    expect(getTaskPollingInterval(baseTask)).toBe(false);
    expect(
      getTaskPollingInterval({
        ...baseTask,
        latest_run: {
          id: "run-1",
          task: "task-1",
          team: 1,
          branch: null,
          environment: "cloud",
          status: "in_progress",
          log_url: "https://example.com/logs",
          error_message: null,
          output: null,
          state: {},
          created_at: "2026-05-13T00:00:00Z",
          updated_at: "2026-05-13T00:00:00Z",
          completed_at: null,
        },
      }),
    ).toBe(5_000);
    expect(
      getTaskPollingInterval([
        {
          ...baseTask,
          latest_run: {
            id: "run-2",
            task: "task-1",
            team: 1,
            branch: null,
            environment: "cloud",
            status: "completed",
            log_url: "https://example.com/logs",
            error_message: null,
            output: null,
            state: {},
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z",
            completed_at: "2026-05-13T00:01:00Z",
          },
        },
        {
          ...baseTask,
          id: "task-2",
          latest_run: {
            id: "run-3",
            task: "task-2",
            team: 1,
            branch: null,
            environment: "cloud",
            status: "in_progress",
            log_url: "https://example.com/logs",
            error_message: null,
            output: null,
            state: {},
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z",
            completed_at: null,
          },
        },
      ]),
    ).toBe(5_000);
  });

  describe("filterListedTasks", () => {
    const run = (environment: string) => ({
      id: "run-1",
      task: "task-1",
      team: 1,
      branch: null,
      environment,
      status: "completed",
      log_url: "https://example.com/logs",
      error_message: null,
      output: null,
      state: {},
      created_at: "2026-05-13T00:00:00Z",
      updated_at: "2026-05-13T00:00:00Z",
      completed_at: "2026-05-13T00:01:00Z",
    });

    it("keeps tasks of any origin except automation by default", () => {
      const tasks = [
        { ...baseTask, id: "a", origin_product: "user_created" },
        { ...baseTask, id: "b", origin_product: "slack" },
        { ...baseTask, id: "c", origin_product: "signal_report" },
        { ...baseTask, id: "d", origin_product: "automation" },
      ];

      expect(filterListedTasks(tasks).map((t) => t.id)).toEqual([
        "a",
        "b",
        "c",
      ]);
    });

    it("keeps automation tasks when they are explicitly requested", () => {
      const tasks = [{ ...baseTask, origin_product: "automation" }];

      expect(filterListedTasks(tasks, "automation")).toHaveLength(1);
    });

    it("always hides desktop-local runs", () => {
      const tasks = [
        { ...baseTask, id: "local", latest_run: run("local") },
        { ...baseTask, id: "cloud", latest_run: run("cloud") },
        { ...baseTask, id: "no-run" },
      ];

      expect(filterListedTasks(tasks).map((t) => t.id)).toEqual([
        "cloud",
        "no-run",
      ]);
    });
  });
});
