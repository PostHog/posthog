import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const updateScoutConfig = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (
    select: (state: { currentProjectId: number | null }) => unknown,
  ) => select({ currentProjectId: 42 }),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => ({ updateScoutConfig }),
}));
const toastError = vi.hoisted(() => vi.fn());
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: toastError },
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { scoutQueryKeys } from "./scoutQueryKeys";
import { useScoutConfigMutations } from "./useScoutConfigMutations";

const CONFIG = {
  id: "config-1",
  skill_name: "signals-scout-error-tracking",
  enabled: true,
  emit: true,
  run_interval_minutes: 1440,
  run_cron_schedule: "0 9 * * 1",
} as ScoutConfig;

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function savedCron(): string | null | undefined {
  return queryClient
    .getQueryData<ScoutConfig[]>(scoutQueryKeys.configs(42))
    ?.find((config) => config.id === CONFIG.id)?.run_cron_schedule;
}

describe("useScoutConfigMutations", () => {
  beforeEach(() => {
    updateScoutConfig.mockReset();
    toastError.mockReset();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(scoutQueryKeys.configs(42), [CONFIG]);
  });

  // Picking weekly reveals the run day picker straight away, so a second choice can be made while
  // the first PATCH is still out. Both writing `run_cron_schedule` at once lets the server commit
  // them in either order and keep the earlier one.
  it("sends a second schedule choice only after the first request settles", async () => {
    let resolveFirst: (config: ScoutConfig) => void = () => {};
    updateScoutConfig
      .mockImplementationOnce(
        () =>
          new Promise<ScoutConfig>((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockImplementation(async (_project, _id, updates) => ({
        ...CONFIG,
        ...updates,
      }));

    const { result } = renderHook(() => useScoutConfigMutations(), { wrapper });

    act(() => {
      void result.current.updateConfig(CONFIG.id, {
        run_cron_schedule: "0 9 * * 1",
      });
      void result.current.updateConfig(CONFIG.id, {
        run_cron_schedule: "0 9 * * 4",
      });
    });

    expect(updateScoutConfig).toHaveBeenCalledTimes(1);
    // The later choice still shows while it waits its turn.
    expect(savedCron()).toBe("0 9 * * 4");

    await act(async () => {
      resolveFirst({ ...CONFIG, run_cron_schedule: "0 9 * * 1" });
    });

    await waitFor(() => expect(updateScoutConfig).toHaveBeenCalledTimes(2));
    expect(updateScoutConfig).toHaveBeenLastCalledWith(42, CONFIG.id, {
      run_cron_schedule: "0 9 * * 4",
    });
    await waitFor(() => expect(savedCron()).toBe("0 9 * * 4"));
  });

  it("rolls the schedule back to the saved one when the write is refused", async () => {
    updateScoutConfig.mockRejectedValue(new Error("Not a valid cron"));

    const { result } = renderHook(() => useScoutConfigMutations(), { wrapper });

    await act(async () => {
      await result.current.updateConfig(CONFIG.id, {
        run_cron_schedule: "0 9 * * 4",
      });
    });

    expect(savedCron()).toBe("0 9 * * 1");
    expect(toastError).toHaveBeenCalledWith("Not a valid cron");
  });
});
