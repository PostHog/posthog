import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const PROJECT_ID = 7;

const mockClient = vi.hoisted(() => ({
  getMyTaskRunConfig: vi.fn(),
  getTeamTaskRunPreferences: vi.fn(),
  updateMyTaskRunPreferences: vi.fn(),
}));
const settingsStore = vi.hoisted(() => ({
  setLastUsedModel: vi.fn(),
  setLastUsedReasoningEffort: vi.fn(),
  setLastUsedAdapter: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (select: (state: unknown) => unknown) =>
    select({ currentProjectId: PROJECT_ID }),
}));
vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: { getState: () => settingsStore },
}));

import { taskRunDefaultsQueryKey } from "@posthog/ui/features/task-detail/hooks/useTaskRunDefaults";
import { useTaskAgentDefaults } from "./useTaskAgentDefaults";

const TEAM_DEFAULT = {
  runtime_adapter: "claude",
  model: "claude-fable-5",
  reasoning_effort: "high",
};
const MY_PICK = {
  runtime_adapter: "codex",
  model: "gpt-5.6-terra",
  reasoning_effort: null,
};

describe("useTaskAgentDefaults", () => {
  let queryClient: QueryClient;

  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  async function mounted() {
    const rendered = renderHook(() => useTaskAgentDefaults(), { wrapper });
    await waitFor(() => expect(rendered.result.current.isLoading).toBe(false));
    return rendered;
  }

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockClient.getMyTaskRunConfig.mockResolvedValue({
      preferences: {
        runtime_adapter: null,
        model: null,
        reasoning_effort: null,
      },
      resolved: { ...TEAM_DEFAULT, source: "team" },
    });
    mockClient.getTeamTaskRunPreferences.mockResolvedValue(TEAM_DEFAULT);
    mockClient.updateMyTaskRunPreferences.mockResolvedValue({
      preferences: MY_PICK,
      resolved: { ...MY_PICK, source: "user" },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  // The composer reads its default from a separate, long-lived cache entry. Twice now a
  // change made here left the task UI opening on the model it replaced, so this pins the
  // link between the two rather than the write on its own.
  it("hands the composer the new default as soon as one is saved", async () => {
    const { result } = await mounted();

    act(() => result.current.save(MY_PICK));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    await waitFor(() =>
      expect(
        queryClient.getQueryData(taskRunDefaultsQueryKey(PROJECT_ID)),
      ).toEqual({ ...MY_PICK, source: "user" }),
    );
    // Seeding alone would leave a mismatched key or an observer elsewhere reading the old
    // value until the stale window expired, so the entry is also marked for refetch.
    expect(
      queryClient.getQueryState(taskRunDefaultsQueryKey(PROJECT_ID))
        ?.isInvalidated,
    ).toBe(true);
  });

  // A device pick outranks the preference when the composer seeds, so leaving it in place
  // shadows the default on any machine that has ever chosen a model.
  it("drops the device's last-used pick so the new default isn't shadowed", async () => {
    const { result } = await mounted();

    act(() => result.current.save(MY_PICK));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    await waitFor(() =>
      expect(settingsStore.setLastUsedModel).toHaveBeenCalledWith(null),
    );
    expect(settingsStore.setLastUsedReasoningEffort).toHaveBeenCalledWith(null);
  });

  // The composer opens on the adapter it last used and skips a default belonging to a
  // different one, so a Claude default set from a composer left on Codex was ignored
  // outright — the model shown never changed.
  it("moves the harness to the one the new default runs on", async () => {
    const claudeDefault = {
      runtime_adapter: "claude",
      model: "claude-opus-4-8",
      reasoning_effort: "medium",
    };
    mockClient.updateMyTaskRunPreferences.mockResolvedValue({
      preferences: claudeDefault,
      resolved: { ...claudeDefault, source: "user" },
    });
    const { result } = await mounted();

    act(() => result.current.save(claudeDefault));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    await waitFor(() =>
      expect(settingsStore.setLastUsedAdapter).toHaveBeenCalledWith("claude"),
    );
  });

  // Picking a model and then its effort is two interactions moments apart; writing on each
  // one is what made the settings row flicker.
  it("coalesces a model-then-effort pick into one write", async () => {
    const { result } = await mounted();

    act(() => result.current.save(MY_PICK));
    act(() => result.current.save({ ...MY_PICK, reasoning_effort: "medium" }));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    await waitFor(() =>
      expect(mockClient.updateMyTaskRunPreferences).toHaveBeenCalledTimes(1),
    );
    expect(mockClient.updateMyTaskRunPreferences).toHaveBeenCalledWith(
      PROJECT_ID,
      { ...MY_PICK, reasoning_effort: "medium" },
    );
  });
});
