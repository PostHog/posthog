import type { TaskCreationOutput } from "@posthog/shared";
import type { Task } from "@posthog/shared/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createTask: vi.fn(),
  resolveModel: vi.fn(),
  openTask: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  track: vi.fn(),
}));
vi.mock("@posthog/di/react", () => ({
  useService: () => ({ createTask: mocks.createTask }),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (selector: (state: { cloudRegion: string }) => unknown) =>
    selector({ cloudRegion: "us" }),
}));
vi.mock("@posthog/ui/features/inbox/hooks/resolveDefaultModel", () => ({
  resolveDefaultModel: mocks.resolveModel,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  reportKeys: { artefacts: (id: string) => ["artefacts", id] },
}));
vi.mock("@posthog/ui/features/integrations/useIntegrations", () => ({
  useUserRepositoryIntegration: () => ({
    getUserIntegrationIdForRepo: () => "integration-1",
  }),
}));
vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: { getState: () => ({}) },
}));
vi.mock("@posthog/ui/features/tasks/useTaskCrudMutations", () => ({
  useCreateTask: () => ({ invalidateTasks: vi.fn() }),
}));
vi.mock("@posthog/ui/hooks/useConnectivity", () => ({
  useConnectivity: () => ({ isOnline: true }),
}));
vi.mock("@posthog/ui/features/notifications/errorDetails", () => ({
  toastError: vi.fn(),
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: {
    loading: vi.fn(),
    dismiss: vi.fn(),
    error: vi.fn(),
    success: mocks.success,
  },
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTask: mocks.openTask }));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: mocks.track }));
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: { scope: () => ({ error: mocks.error }) },
}));

import { useInboxCloudTaskRunner } from "./useInboxCloudTaskRunner";

const task = {
  id: "implementation-1",
  title: "Fix the example report",
} as Task;
const output = { task, workspace: null } as TaskCreationOutput;

function renderRunner() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onTaskStarted = vi.fn();
  const hook = renderHook(
    () =>
      useInboxCloudTaskRunner({
        reportId: "report-1",
        cloudRepository: "example/project",
        loggerScope: "test",
        redirectOnSuccess: false,
        onTaskStarted,
        copy: {
          loadingTitle: "Starting PR task",
          errorTitle: "Could not start PR task",
          missingRepository: "Choose a repository",
          missingIntegration: "Connect GitHub",
          signedOut: "Sign in",
          missingModel: "Choose a model",
        },
        buildInput: () => ({ content: "Create a PR", workspaceMode: "cloud" }),
      }),
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      ),
    },
  );
  return { ...hook, onTaskStarted, queryClient };
}

describe("useInboxCloudTaskRunner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.resolveModel.mockResolvedValue("claude-sonnet-4-6");
  });

  it.each([true, false])(
    "waits for startup to finish before handing off (success: %s)",
    async (success) => {
      let settle!: (result: unknown) => void;
      mocks.createTask.mockImplementation((_input, onReady) => {
        onReady(output);
        return new Promise((resolve) => {
          settle = resolve;
        });
      });
      const { result, onTaskStarted } = renderRunner();
      let pending!: Promise<boolean>;
      act(() => {
        pending = result.current.run();
      });
      await waitFor(() => expect(mocks.createTask).toHaveBeenCalledOnce());
      expect(onTaskStarted).not.toHaveBeenCalled();
      expect(mocks.openTask).not.toHaveBeenCalled();
      expect(mocks.success).not.toHaveBeenCalled();
      expect(result.current.isRunning).toBe(true);
      await act(async () => {
        settle(
          success
            ? { success: true, data: output }
            : { success: false, error: "Startup failed" },
        );
        expect(await pending).toBe(success);
      });
      expect(onTaskStarted).toHaveBeenCalledTimes(success ? 1 : 0);
      expect(result.current.isRunning).toBe(false);
      expect(mocks.openTask).not.toHaveBeenCalled();
      expect(
        mocks.track.mock.calls.filter(([event]) => event === "Task created"),
      ).toEqual(
        success
          ? [["Task created", expect.objectContaining({ task_id: task.id })]]
          : [],
      );
      if (success) {
        const options = mocks.success.mock.calls[0][1];
        expect(options.action.label).toBe("View task");
        options.action.onClick();
        expect(mocks.openTask).toHaveBeenCalledWith(task);
      }
    },
  );

  it("keeps successful startup when the handoff callback throws", async () => {
    mocks.createTask.mockResolvedValue({ success: true, data: output });
    const { result, onTaskStarted, queryClient } = renderRunner();
    const refresh = vi.spyOn(queryClient, "invalidateQueries");
    const error = new Error("Handoff failed");
    onTaskStarted.mockImplementation(() => {
      throw error;
    });
    await act(async () => {
      expect(await result.current.run()).toBe(true);
    });
    expect(mocks.error).toHaveBeenCalledWith(
      "Task started, but the handoff callback failed",
      error,
    );
    expect(refresh).toHaveBeenCalledWith({
      queryKey: ["inbox", "signal-reports"],
    });
    expect(mocks.success).toHaveBeenCalledOnce();
    expect(result.current.isRunning).toBe(false);
    expect(mocks.createTask).toHaveBeenCalledOnce();
  });

  it("blocks repeated clicks and permits retry after model lookup fails", async () => {
    mocks.resolveModel.mockRejectedValueOnce(new Error("Model lookup failed"));
    mocks.createTask.mockResolvedValue({ success: true, data: output });
    const { result, onTaskStarted } = renderRunner();
    await act(async () => {
      const first = result.current.run();
      const duplicate = result.current.run();
      expect(await duplicate).toBe(false);
      expect(await first).toBe(false);
    });
    expect(result.current.isRunning).toBe(false);
    expect(onTaskStarted).not.toHaveBeenCalled();
    expect(mocks.createTask).not.toHaveBeenCalled();
    expect(
      mocks.track.mock.calls.filter(([event]) => event === "Task created"),
    ).toEqual([]);
    await act(async () => {
      expect(await result.current.run()).toBe(true);
    });
    expect(mocks.createTask).toHaveBeenCalledOnce();
    expect(onTaskStarted).toHaveBeenCalledOnce();
    expect(
      mocks.track.mock.calls.filter(([event]) => event === "Task created"),
    ).toEqual([
      ["Task created", expect.objectContaining({ task_id: task.id })],
    ]);
  });
});
