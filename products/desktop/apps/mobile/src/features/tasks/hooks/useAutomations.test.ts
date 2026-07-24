import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type PropsWithChildren } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  mockUseAuthStore,
  mockGetTaskAutomations,
  mockCreateTaskAutomation,
  mockUpdateTaskAutomation,
} = vi.hoisted(() => ({
  mockUseAuthStore: vi.fn(),
  mockGetTaskAutomations: vi.fn(),
  mockCreateTaskAutomation: vi.fn(),
  mockUpdateTaskAutomation: vi.fn(),
}));

vi.mock("@/features/auth", () => ({
  useAuthStore: mockUseAuthStore,
}));

vi.mock("../api", () => ({
  getTaskAutomations: mockGetTaskAutomations,
  getTaskAutomation: vi.fn(),
  createTaskAutomation: mockCreateTaskAutomation,
  updateTaskAutomation: mockUpdateTaskAutomation,
  deleteTaskAutomation: vi.fn(),
  runTaskAutomation: vi.fn(),
}));

import {
  automationKeys,
  getAutomationPollingInterval,
  useAutomations,
  useCreateTaskAutomation,
  useUpdateTaskAutomation,
} from "./useAutomations";
import { taskKeys } from "./useTasks";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      children,
    );
  };
}

function renderTestHook<Result>(
  useHook: () => Result,
  wrapper:
    | ((props: PropsWithChildren) => ReturnType<typeof createElement>)
    | undefined,
) {
  let currentResult: Result;

  function HookProbe() {
    currentResult = useHook();
    return null;
  }

  function TestTree() {
    if (!wrapper) {
      return createElement(HookProbe);
    }

    const Wrapper = wrapper;
    return createElement(Wrapper, null, createElement(HookProbe));
  }

  let renderer: ReturnType<typeof create>;
  act(() => {
    renderer = create(createElement(TestTree));
  });

  return {
    result: {
      get current() {
        return currentResult;
      },
    },
    unmount() {
      act(() => {
        renderer.unmount();
      });
    },
  };
}

async function waitForAssertion(assertion: () => void): Promise<void> {
  const timeoutAt = Date.now() + 2_000;

  while (Date.now() < timeoutAt) {
    try {
      assertion();
      return;
    } catch (error) {
      await new Promise((resolve) => setTimeout(resolve, 10));
      if (Date.now() >= timeoutAt) {
        throw error;
      }
    }
  }
}

const automationPayload = {
  id: "automation-1",
  name: "Daily PRs",
  prompt: "Check PRs",
  repository: "posthog/posthog",
  github_integration: 7,
  cron_expression: "0 9 * * *",
  timezone: "Europe/London",
  template_id: "llm-skill:shared-daily-brief",
  enabled: true,
  last_run_at: null,
  last_run_status: null,
  last_task_id: "task-1",
  last_task_run_id: null,
  last_error: null,
  created_at: "2026-05-13T00:00:00Z",
  updated_at: "2026-05-13T00:00:00Z",
};

describe("useAutomations", () => {
  beforeEach(() => {
    mockUseAuthStore.mockImplementation((selector) =>
      selector
        ? selector({
            projectId: 42,
            oauthAccessToken: "token",
          })
        : {
            projectId: 42,
            oauthAccessToken: "token",
          },
    );
    mockGetTaskAutomations.mockReset();
    mockCreateTaskAutomation.mockReset();
    mockUpdateTaskAutomation.mockReset();
  });

  it("loads automation lists through the dedicated query key", async () => {
    mockGetTaskAutomations.mockResolvedValueOnce([automationPayload]);

    const queryClient = new QueryClient();
    const { result, unmount } = renderTestHook(
      () => useAutomations(),
      createWrapper(queryClient),
    );

    await waitForAssertion(() => {
      expect(result.current.automations).toHaveLength(1);
    });

    expect(mockGetTaskAutomations).toHaveBeenCalledOnce();
    expect(queryClient.getQueryData(automationKeys.list())).toEqual([
      automationPayload,
    ]);
    unmount();
  });

  it("only polls automation queries while a run is still active", () => {
    expect(getAutomationPollingInterval(undefined)).toBe(false);
    expect(getAutomationPollingInterval(automationPayload)).toBe(false);
    expect(
      getAutomationPollingInterval({
        ...automationPayload,
        last_run_status: "running",
      }),
    ).toBe(5_000);
    expect(
      getAutomationPollingInterval([
        automationPayload,
        {
          ...automationPayload,
          id: "automation-2",
          last_run_status: "running",
        },
      ]),
    ).toBe(5_000);
  });

  it("invalidates automation and task lists after create", async () => {
    const queryClient = new QueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    mockCreateTaskAutomation.mockResolvedValueOnce(automationPayload);

    const { result, unmount } = renderTestHook(
      () => useCreateTaskAutomation(),
      createWrapper(queryClient),
    );

    await act(async () => {
      await result.current.mutateAsync({
        name: "Daily PRs",
        prompt: "Check PRs",
        repository: "posthog/posthog",
        github_integration: 7,
        cron_expression: "0 9 * * *",
        timezone: "Europe/London",
        template_id: "llm-skill:shared-daily-brief",
      });
    });

    expect(mockCreateTaskAutomation).toHaveBeenCalledWith({
      name: "Daily PRs",
      prompt: "Check PRs",
      repository: "posthog/posthog",
      github_integration: 7,
      cron_expression: "0 9 * * *",
      timezone: "Europe/London",
      template_id: "llm-skill:shared-daily-brief",
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: automationKeys.lists(),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: taskKeys.lists(),
    });
    unmount();
  });

  it("updates the detail cache immediately after automation edits", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(
      automationKeys.detail("automation-1"),
      automationPayload,
    );
    mockUpdateTaskAutomation.mockResolvedValueOnce({
      ...automationPayload,
      enabled: false,
      cron_expression: "30 14 * * *",
    });

    const { result, unmount } = renderTestHook(
      () => useUpdateTaskAutomation(),
      createWrapper(queryClient),
    );

    await act(async () => {
      await result.current.mutateAsync({
        automationId: "automation-1",
        updates: {
          enabled: false,
          cron_expression: "30 14 * * *",
        },
      });
    });

    expect(
      queryClient.getQueryData(automationKeys.detail("automation-1")),
    ).toMatchObject({
      enabled: false,
      cron_expression: "30 14 * * *",
      template_id: "llm-skill:shared-daily-brief",
    });
    unmount();
  });

  it("does not populate automation caches when creation fails", async () => {
    const queryClient = new QueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    mockCreateTaskAutomation.mockRejectedValueOnce(
      new Error("Repository is still required for this template."),
    );

    const { result, unmount } = renderTestHook(
      () => useCreateTaskAutomation(),
      createWrapper(queryClient),
    );

    await expect(
      result.current.mutateAsync({
        name: "Shared daily brief",
        prompt: "Summarize feature usage for my product areas.",
        repository: "",
        github_integration: null,
        cron_expression: "0 8 * * 1-5",
        timezone: "America/New_York",
        template_id: "llm-skill:shared-daily-brief",
      }),
    ).rejects.toThrow("Repository is still required for this template.");

    expect(
      queryClient.getQueryData(automationKeys.detail("automation-1")),
    ).toBe(undefined);
    expect(invalidateSpy).not.toHaveBeenCalled();
    unmount();
  });
});
