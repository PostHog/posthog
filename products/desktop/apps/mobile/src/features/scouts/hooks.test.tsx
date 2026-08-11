import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

const { mockListScoutConfigs, mockUpdateScoutConfig, mockRunScoutConfig } =
  vi.hoisted(() => ({
    mockListScoutConfigs: vi.fn(),
    mockUpdateScoutConfig: vi.fn(),
    mockRunScoutConfig: vi.fn(),
  }));

vi.mock("@/lib/posthogApiClient", () => ({
  getPostHogApiClient: () => ({
    listScoutConfigs: mockListScoutConfigs,
    updateScoutConfig: mockUpdateScoutConfig,
    runScoutConfig: mockRunScoutConfig,
  }),
}));
vi.mock("@/features/auth", () => ({
  useAuthStore: () => ({ projectId: 2, oauthAccessToken: "token" }),
}));

import { scoutKeys, useScoutConfigMutations, useScoutConfigs } from "./hooks";

function config(overrides: Partial<ScoutConfig> = {}): ScoutConfig {
  return {
    id: "config-1",
    skill_name: "signals-scout-errors",
    enabled: true,
    emit: true,
    run_interval_minutes: 60,
    last_run_at: null,
    created_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

function renderScouts() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  let latest: {
    configs: ReturnType<typeof useScoutConfigs>;
    mutations: ReturnType<typeof useScoutConfigMutations>;
  } | null = null;

  function Harness() {
    latest = {
      configs: useScoutConfigs(),
      mutations: useScoutConfigMutations(),
    };
    return null;
  }

  act(() => {
    create(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(Harness),
      ),
    );
  });
  return {
    current: () => {
      if (!latest) throw new Error("harness did not render");
      return latest;
    },
    queryClient,
  };
}

async function waitUntil(cond: () => boolean) {
  for (let i = 0; i < 40; i++) {
    if (cond()) return;
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
  throw new Error("condition not met within the wait budget");
}

function cachedConfigs(queryClient: QueryClient): ScoutConfig[] {
  return queryClient.getQueryData<ScoutConfig[]>(scoutKeys.configs()) ?? [];
}

describe("useScoutConfigs", () => {
  it("exposes the project's scout fleet", async () => {
    mockListScoutConfigs.mockResolvedValue([config(), config({ id: "b" })]);
    const harness = renderScouts();

    await waitUntil(() => (harness.current().configs.data?.length ?? 0) === 2);
    expect(mockListScoutConfigs).toHaveBeenCalledWith(2);
  });
});

describe("useScoutConfigMutations", () => {
  it("applies a disable optimistically and settles on the server's config", async () => {
    mockListScoutConfigs.mockResolvedValueOnce([config()]);
    let resolveUpdate: (value: ScoutConfig) => void = () => {};
    mockUpdateScoutConfig.mockReturnValue(
      new Promise<ScoutConfig>((resolve) => {
        resolveUpdate = resolve;
      }),
    );
    const harness = renderScouts();
    await waitUntil(() => cachedConfigs(harness.queryClient).length === 1);

    act(() => {
      harness.current().mutations.updateConfig.mutate({
        configId: "config-1",
        updates: { enabled: false },
      });
    });

    await waitUntil(
      () => cachedConfigs(harness.queryClient)[0].enabled === false,
    );
    expect(mockUpdateScoutConfig).toHaveBeenCalledWith(2, "config-1", {
      enabled: false,
    });

    // The server's answer carries the lifecycle fields the optimistic patch
    // could not know about.
    mockListScoutConfigs.mockResolvedValue([
      config({ enabled: false, status: "paused_by_user" }),
    ]);
    await act(async () => {
      resolveUpdate(config({ enabled: false, status: "paused_by_user" }));
    });

    await waitUntil(
      () => cachedConfigs(harness.queryClient)[0].status === "paused_by_user",
    );
  });

  it("rolls the optimistic update back when the server rejects it", async () => {
    mockListScoutConfigs.mockResolvedValue([config()]);
    mockUpdateScoutConfig.mockRejectedValue(new Error("nope"));
    const harness = renderScouts();
    await waitUntil(() => cachedConfigs(harness.queryClient).length === 1);

    act(() => {
      harness.current().mutations.updateConfig.mutate({
        configId: "config-1",
        updates: { run_interval_minutes: 1440 },
      });
    });

    await waitUntil(() => mockUpdateScoutConfig.mock.calls.length === 1);
    await waitUntil(
      () => cachedConfigs(harness.queryClient)[0].run_interval_minutes === 60,
    );
  });

  it("triggers a manual run and refreshes the runs window", async () => {
    mockListScoutConfigs.mockResolvedValue([config()]);
    mockRunScoutConfig.mockResolvedValue({
      skill_name: "signals-scout-errors",
      workflow_id: "wf-1",
      started: true,
    });
    const harness = renderScouts();
    const invalidate = vi.spyOn(harness.queryClient, "invalidateQueries");

    act(() => {
      harness.current().mutations.runScout.mutate("config-1");
    });

    await waitUntil(
      () => harness.current().mutations.runScout.isSuccess === true,
    );
    expect(mockRunScoutConfig).toHaveBeenCalledWith(2, "config-1");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: scoutKeys.runs() });
  });

  it("surfaces the server's explanation when a run is already in progress", async () => {
    mockListScoutConfigs.mockResolvedValue([config()]);
    mockRunScoutConfig.mockRejectedValue(
      new Error("A run for this scout is already in progress."),
    );
    const harness = renderScouts();

    act(() => {
      harness.current().mutations.runScout.mutate("config-1");
    });

    await waitUntil(
      () => harness.current().mutations.runScout.isError === true,
    );
    expect(harness.current().mutations.runScout.error?.message).toBe(
      "A run for this scout is already in progress.",
    );
  });
});
