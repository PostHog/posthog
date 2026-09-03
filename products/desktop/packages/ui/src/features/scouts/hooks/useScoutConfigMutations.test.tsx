import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { scoutQueryKeys } from "./scoutQueryKeys";
import { useScoutConfigMutations } from "./useScoutConfigMutations";

const PROJECT_ID = 42;

const updateScoutConfig = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
const track = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => ({ updateScoutConfig }),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (sel: (s: { currentProjectId: number }) => unknown) =>
    sel({ currentProjectId: PROJECT_ID }),
}));
vi.mock("@posthog/core/scouts/scoutPresentation", () => ({
  getScoutOrigin: () => "canonical",
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track }));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: toastError },
}));

function makeConfig(overrides: Partial<ScoutConfig> = {}): ScoutConfig {
  return {
    id: "config-1",
    skill_name: "error-tracking",
    enabled: true,
    emit: true,
    run_interval_minutes: 60,
    last_run_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderWithConfig(config: ScoutConfig) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const queryKey = scoutQueryKeys.configs(PROJECT_ID);
  queryClient.setQueryData<ScoutConfig[]>(queryKey, [config]);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useScoutConfigMutations(), { wrapper });
  const read = () => queryClient.getQueryData<ScoutConfig[]>(queryKey)?.[0];
  return { result, read };
}

describe("useScoutConfigMutations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    { name: "sets a model pin", input: "claude-opus-4-5" },
    { name: "clears a model pin", input: null },
  ])("$name and reconciles with the server response", async ({ input }) => {
    const config = makeConfig({ model: "claude-sonnet-4" });
    // The server may normalize the value, so the cache must reflect what it
    // returns, not the optimistic guess.
    updateScoutConfig.mockResolvedValue(makeConfig({ model: input }));
    const { result, read } = renderWithConfig(config);

    await result.current.updateConfig(config.id, { model: input });

    expect(updateScoutConfig).toHaveBeenCalledWith(PROJECT_ID, config.id, {
      model: input,
    });
    expect(read()?.model).toBe(input);
  });

  it("rolls the config back when the PATCH fails", async () => {
    const config = makeConfig({ model: "claude-sonnet-4" });
    updateScoutConfig.mockRejectedValue(new Error("nope"));
    const { result, read } = renderWithConfig(config);

    await result.current.updateConfig(config.id, { model: "claude-opus-4-5" });

    expect(read()?.model).toBe("claude-sonnet-4");
    expect(toastError).toHaveBeenCalled();
  });

  // The model input is free text, so a user could type private text the server
  // rejects. Analytics must record only that a pin was set, never the text.
  it.each([
    { name: "on success", success: true },
    { name: "on a rejected PATCH", success: false },
  ])(
    "reports whether a model pin is set, never the typed text, $name",
    async ({ success }) => {
      const config = makeConfig({ model: null });
      const typed = "sk-not-a-real-model";
      if (success) {
        updateScoutConfig.mockResolvedValue(makeConfig({ model: typed }));
      } else {
        updateScoutConfig.mockRejectedValue(new Error("nope"));
      }
      const { result } = renderWithConfig(config);

      await result.current.updateConfig(config.id, { model: typed });

      expect(track).toHaveBeenCalledTimes(1);
      expect(track.mock.calls[0][1]).toMatchObject({
        setting: "model",
        new_value: true,
        old_value: false,
        success,
      });
      expect(JSON.stringify(track.mock.calls[0])).not.toContain(typed);
    },
  );
});
