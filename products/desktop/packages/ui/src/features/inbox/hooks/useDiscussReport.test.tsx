import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createTask = vi.hoisted(() =>
  vi.fn().mockResolvedValue({
    success: true,
    task: { id: "task-1" },
  }),
);
const getUserIntegrationIdForRepo = vi.hoisted(() => vi.fn(() => "ghu_1"));
const openTask = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const toastError = vi.hoisted(() => vi.fn());
const resolveDefaultModel = vi.hoisted(() =>
  vi.fn().mockResolvedValue("claude-sonnet"),
);

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (sel: (s: { cloudRegion: string }) => unknown) =>
    sel({ cloudRegion: "us" }),
}));
vi.mock("@posthog/ui/features/integrations/useIntegrations", () => ({
  useUserRepositoryIntegration: () => ({ getUserIntegrationIdForRepo }),
}));
vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: {
    getState: () => ({
      lastUsedAdapter: "claude",
      lastUsedModel: "claude-sonnet",
      lastUsedReasoningEffort: undefined,
    }),
  },
}));
// The runner resolves two distinct services off the container (the task service
// and the report model resolver); return the right shape per token so the model
// resolver isn't silently `{ createTask }` (which would make every run blocked).
vi.mock("@posthog/di/react", () => ({
  useService: (token: symbol) =>
    token.description === "posthog.core.inbox.reportModelResolver"
      ? { resolveDefaultModel }
      : { createTask },
}));
vi.mock("@posthog/ui/features/tasks/useTaskCrudMutations", () => ({
  useCreateTask: () => ({ invalidateTasks: vi.fn() }),
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTask,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: { scope: () => ({ info: vi.fn(), error: vi.fn(), warn: vi.fn() }) },
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: {
    error: toastError,
    loading: vi.fn(() => "toast-1"),
    dismiss: vi.fn(),
  },
}));

import { useDiscussReport } from "./useDiscussReport";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useDiscussReport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getUserIntegrationIdForRepo.mockReturnValue("ghu_1");
    createTask.mockResolvedValue({ success: true, task: { id: "task-1" } });
  });

  it("skips task creation and shows an error when no cloud repository is set", async () => {
    const { result } = renderHook(
      () =>
        useDiscussReport({
          reportId: "r1",
          reportTitle: "T",
          cloudRepository: null,
        }),
      { wrapper: createWrapper() },
    );
    await result.current.discussReport("why?");
    expect(createTask).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith(
      "Failed to start discussion",
      expect.objectContaining({
        description: "Pick a cloud repository before starting a discussion",
      }),
    );
  });

  it("creates a cloud signal_report task through the service when valid", async () => {
    const { result } = renderHook(
      () =>
        useDiscussReport({
          reportId: "r1",
          reportTitle: "T",
          cloudRepository: "owner/repo",
        }),
      { wrapper: createWrapper() },
    );
    await result.current.discussReport("why?");
    expect(createTask).toHaveBeenCalledTimes(1);
    const input = createTask.mock.calls[0][0];
    expect(input.repository).toBe("owner/repo");
    expect(input.githubUserIntegrationId).toBe("ghu_1");
    expect(input.workspaceMode).toBe("cloud");
    expect(input.cloudRunSource).toBe("signal_report");
    expect(input.signalReportId).toBe("r1");
  });
});
