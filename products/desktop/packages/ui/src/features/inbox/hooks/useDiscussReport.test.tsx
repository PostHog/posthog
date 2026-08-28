import type { SignalReport } from "@posthog/shared/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
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
const getSignalReportSignals = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (sel: (s: { cloudRegion: string }) => unknown) =>
    sel({ cloudRegion: "us" }),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({ getSignalReportSignals }),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  AUTH_SCOPED_QUERY_META: {},
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

const report = {
  id: "r1",
  title: "Return 400 instead of 500",
  summary: "A malformed PUT raises a bare KeyError.",
  status: "ready",
  created_at: "2026-08-20T12:00:00Z",
  updated_at: "2026-08-20T12:00:00Z",
} as SignalReport;

describe("useDiscussReport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createTask.mockResolvedValue({ success: true, task: { id: "task-1" } });
    getSignalReportSignals.mockResolvedValue({
      report: null,
      signals: [
        {
          signal_id: "sig-1",
          content: "New error tracking issue: KeyError 'resource'",
          source_product: "error_tracking",
          source_type: "issue",
          source_id: "issue-1",
          weight: 1,
          timestamp: "2026-08-20T11:00:00Z",
          extra: {},
        },
      ],
    });
  });

  it("creates a repo-less signal_report task with the full report inlined", async () => {
    const { result } = renderHook(() => useDiscussReport({ report }), {
      wrapper: createWrapper(),
    });
    await result.current.discussReport("why?");
    expect(createTask).toHaveBeenCalledTimes(1);
    const input = createTask.mock.calls[0][0];
    // The backend rejects a client-set repo for signal-report tasks.
    expect(input.repository).toBeUndefined();
    expect(input.githubUserIntegrationId).toBeUndefined();
    expect(input.workspaceMode).toBe("cloud");
    expect(input.cloudRunSource).toBe("signal_report");
    expect(input.signalReportId).toBe("r1");
    // Routed to the discussion cap, not the report's one-live-PR gate.
    expect(input.signalReportTaskRelationship).toBe("discussion");
    // First message: question leading, whole report + evidence behind it.
    expect(input.content).toContain("Answer this first: why?");
    expect(input.content).toContain("# Report: Return 400 instead of 500");
    expect(input.content).toContain("A malformed PUT raises a bare KeyError.");
    expect(input.content).toContain("KeyError 'resource'");
    // Task record stays short — the report lives in the message, not the title.
    expect(input.taskDescription).toBe(
      "Discuss report: Return 400 instead of 500 — why?",
    );
  });

  it("reads in-flight from the click and ignores a re-entrant request", async () => {
    let resolveSignals: (value: unknown) => void = () => {};
    getSignalReportSignals.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSignals = resolve;
        }),
    );
    const { result } = renderHook(() => useDiscussReport({ report }), {
      wrapper: createWrapper(),
    });
    expect(result.current.isDiscussing).toBe(false);

    let first: Promise<void> = Promise.resolve();
    await act(async () => {
      first = result.current.discussReport("first");
    });
    // The evidence fetch is still pending, but the button must already be busy.
    expect(result.current.isDiscussing).toBe(true);

    let second: Promise<void> = Promise.resolve();
    await act(async () => {
      // A second click while in flight is ignored, so it can't overwrite the
      // pending question or start a duplicate task.
      second = result.current.discussReport("second");
      resolveSignals({ report: null, signals: [] });
      await Promise.all([first, second]);
    });

    expect(result.current.isDiscussing).toBe(false);
    expect(createTask).toHaveBeenCalledTimes(1);
    expect(createTask.mock.calls[0][0].content).toContain(
      "Answer this first: first",
    );
  });

  it("still starts the discussion with summary-only context when the signals fetch fails", async () => {
    getSignalReportSignals.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useDiscussReport({ report }), {
      wrapper: createWrapper(),
    });
    await result.current.discussReport();
    expect(createTask).toHaveBeenCalledTimes(1);
    const input = createTask.mock.calls[0][0];
    expect(input.content).toContain("A malformed PUT raises a bare KeyError.");
    expect(input.content).not.toContain("## Evidence");
    expect(toastError).not.toHaveBeenCalled();
  });
});
