import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ configs: vi.fn() }));
vi.mock("../hooks/useScoutConfigs", () => ({
  useScoutConfigs: mocks.configs,
}));
vi.mock("../hooks/useScoutFleetSync", () => ({
  useScoutFleetSync: () => ({ isSyncing: false, syncOutcome: "synced" }),
}));
vi.mock("../hooks/useScoutRecentRuns", () => ({
  useScoutRecentRuns: () => ({
    data: [],
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useScoutOutputSummary: () => ({ data: undefined, isError: false }),
}));
vi.mock("../hooks/useScoutSkillCreators", () => ({
  useScoutSkillCreators: () => ({ data: undefined }),
}));
vi.mock("../hooks/useScoutSuggestions", () => ({
  useScoutSuggestions: () => ({ data: undefined }),
  useDismissScoutSuggestion: () => vi.fn(),
}));
vi.mock("../hooks/useScoutConfigMutations", () => ({
  useScoutConfigMutations: () => ({ updateConfig: vi.fn() }),
}));
vi.mock("../hooks/useTrackFleetViewed", () => ({
  useTrackFleetViewed: () => undefined,
}));
vi.mock("../../auth/useMeQuery", () => ({
  useMeQuery: () => ({ data: undefined }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: React.ReactNode }) => (
    <span>{children}</span>
  ),
}));
vi.mock("./ScoutTable", () => ({
  ScoutTable: ({ configs }: { configs: ScoutConfig[] }) => (
    <ol data-testid="rows">
      {configs.map((config) => (
        <li key={config.id}>{config.skill_name}</li>
      ))}
    </ol>
  ),
}));

import { ScoutsFleetView } from "./ScoutsFleetView";

function makeConfig(overrides: Partial<ScoutConfig>): ScoutConfig {
  return {
    id: overrides.skill_name ?? "config",
    skill_name: "signals-scout-logs",
    enabled: true,
    emit: true,
    run_interval_minutes: 60,
    last_run_at: null,
    created_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

function rowOrder(): string[] {
  return Array.from(screen.getByTestId("rows").children).map(
    (row) => row.textContent ?? "",
  );
}

describe("ScoutsFleetView", () => {
  beforeEach(() => {
    mocks.configs.mockReturnValue({
      data: [
        makeConfig({
          skill_name: "signals-scout-apm",
          created_at: "2026-06-02T00:00:00Z",
        }),
        makeConfig({
          skill_name: "signals-scout-logs",
          created_at: "2026-06-08T00:00:00Z",
        }),
      ],
      isLoading: false,
      isError: false,
      isFetching: false,
      isFetchedAfterMount: true,
      refetch: vi.fn(),
    });
  });

  it("reorders the fleet when the user picks a recency sort", () => {
    render(<ScoutsFleetView onNewAgent={vi.fn()} />);
    expect(rowOrder()).toEqual(["signals-scout-apm", "signals-scout-logs"]);

    fireEvent.click(screen.getByLabelText("Sort agents"));
    fireEvent.click(screen.getByText("Sort: Recently created"));

    expect(rowOrder()).toEqual(["signals-scout-logs", "signals-scout-apm"]);
  });
});
