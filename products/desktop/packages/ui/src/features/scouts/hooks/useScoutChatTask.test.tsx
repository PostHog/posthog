import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createTask = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ success: true, task: { id: "task-1" } }),
);
const getUserIntegrationIdForRepo = vi.hoisted(() => vi.fn(() => "ghu_1"));
const resolveDefaultCloudRepository = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (sel: (s: { cloudRegion: string }) => unknown) =>
    sel({ cloudRegion: "us" }),
}));
vi.mock("@posthog/ui/hooks/useConnectivity", () => ({
  useConnectivity: () => ({ isOnline: true }),
}));
vi.mock("@posthog/ui/features/connectivity/connectivityToast", () => ({
  showOfflineToast: vi.fn(),
}));
vi.mock("@posthog/ui/features/inbox/hooks/resolveDefaultModel", () => ({
  resolveDefaultModel: vi.fn().mockResolvedValue("claude-sonnet"),
}));
vi.mock("@posthog/ui/features/integrations/useIntegrations", () => ({
  useUserRepositoryIntegration: () => ({
    repositories: [],
    getUserIntegrationIdForRepo,
  }),
}));
vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  resolveDefaultCloudRepository,
  useSettingsStore: Object.assign(
    (sel: (s: { lastUsedCloudRepository: string | null }) => unknown) =>
      sel({ lastUsedCloudRepository: null }),
    {
      getState: () => ({
        lastUsedAdapter: "claude",
        lastUsedModel: "claude-sonnet",
        lastUsedReasoningEffort: undefined,
      }),
    },
  ),
}));
vi.mock("@posthog/di/react", () => ({
  useService: (token: symbol) =>
    token.description === "posthog.core.inbox.reportModelResolver"
      ? { resolveDefaultModel: vi.fn() }
      : { createTask },
}));
vi.mock("@posthog/ui/features/tasks/useTaskCrudMutations", () => ({
  useCreateTask: () => ({ invalidateTasks: vi.fn() }),
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTask: vi.fn().mockResolvedValue(undefined),
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
    success: vi.fn(),
  },
}));

import { useScoutChatTask } from "./useScoutChatTask";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function renderRunTask() {
  return renderHook(
    () =>
      useScoutChatTask({
        prompt: "Make a scout",
        taskLabel: "scout authoring",
        loggerScope: "scout-author",
        chatType: "author_scout",
        surface: "fleet_list",
      }),
    { wrapper: createWrapper() },
  );
}

describe("useScoutChatTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates a repo-less cloud task when no personal repo is resolvable", async () => {
    // The PR #2986 scenario: team integration only, no personal install, so no
    // user-level repo resolves. Scout authoring is pure PostHog-MCP work, so it
    // must still run rather than failing with a "connect GitHub" toast.
    resolveDefaultCloudRepository.mockReturnValue(null);

    const { result } = renderRunTask();
    await result.current.runTask();

    expect(toastError).not.toHaveBeenCalled();
    expect(createTask).toHaveBeenCalledTimes(1);
    const input = createTask.mock.calls[0][0];
    expect(input.repository).toBeNull();
    expect(input.githubUserIntegrationId).toBeUndefined();
    expect(input.workspaceMode).toBe("cloud");
    expect(getUserIntegrationIdForRepo).not.toHaveBeenCalled();
  });

  it("passes the resolved repo through when one is available", async () => {
    resolveDefaultCloudRepository.mockReturnValue("owner/repo");

    const { result } = renderRunTask();
    await result.current.runTask();

    expect(createTask).toHaveBeenCalledTimes(1);
    const input = createTask.mock.calls[0][0];
    expect(input.repository).toBe("owner/repo");
    expect(input.githubUserIntegrationId).toBe("ghu_1");
  });
});
