import type { SignalSourceConfig } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  teams: [
    { id: "team-eng", name: "Engineering" },
    { id: "team-support", name: "Support" },
  ] as { id: string; name: string }[],
  status: "ready" as "loading" | "missing" | "error" | "ready",
  createSignalSourceConfig: vi.fn(),
  updateSignalSourceConfig: vi.fn(),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useLinearTeams", () => ({
  useLinearTeams: () => ({ teams: mocks.teams, status: mocks.status }),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    createSignalSourceConfig: mocks.createSignalSourceConfig,
    updateSignalSourceConfig: mocks.updateSignalSourceConfig,
  }),
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: () => 42,
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { LinearTeamsDialog } from "./LinearTeamsDialog";

function linearConfig(
  config: Record<string, unknown>,
  enabled = true,
): SignalSourceConfig {
  return {
    id: "config-1",
    source_product: "linear",
    source_type: "issue",
    enabled,
    config,
    created_at: "2026-06-05T00:00:00Z",
    updated_at: "2026-06-05T00:00:00Z",
    status: null,
  };
}

function renderDialog(props: {
  config: SignalSourceConfig | null;
  enableOnSave: boolean;
}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LinearTeamsDialog
        config={props.config}
        enableOnSave={props.enableOnSave}
        viaSetupWizard={false}
        open
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("LinearTeamsDialog", () => {
  beforeEach(() => {
    mocks.teams = [
      { id: "team-eng", name: "Engineering" },
      { id: "team-support", name: "Support" },
    ];
    mocks.status = "ready";
    mocks.createSignalSourceConfig.mockReset();
    mocks.updateSignalSourceConfig.mockReset();
  });
  afterEach(cleanup);

  it("enables the source reading every team", async () => {
    renderDialog({ config: null, enableOnSave: true });

    await userEvent.click(
      screen.getByRole("button", { name: "Turn on Linear" }),
    );

    await waitFor(() =>
      expect(mocks.createSignalSourceConfig).toHaveBeenCalledWith(42, {
        source_product: "linear",
        source_type: "issue",
        enabled: true,
        config: { linear_team_ids: [] },
      }),
    );
  });

  it("enables the source reading only the picked teams", async () => {
    renderDialog({ config: null, enableOnSave: true });

    await userEvent.click(screen.getByText("Only the teams I pick"));
    await userEvent.click(screen.getByText("Support"));
    await userEvent.click(
      screen.getByRole("button", { name: "Turn on Linear" }),
    );

    await waitFor(() =>
      expect(mocks.createSignalSourceConfig).toHaveBeenCalledWith(
        42,
        expect.objectContaining({
          config: { linear_team_ids: ["team-support"] },
        }),
      ),
    );
  });

  it("keeps the rest of the config when the scope is edited later", async () => {
    renderDialog({
      config: linearConfig({
        steering: "Skip chores",
        linear_team_ids: ["team-eng"],
      }),
      enableOnSave: false,
    });

    await userEvent.click(screen.getByText("Support"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mocks.updateSignalSourceConfig).toHaveBeenCalledWith(
        42,
        "config-1",
        {
          enabled: true,
          config: {
            steering: "Skip chores",
            linear_team_ids: ["team-eng", "team-support"],
          },
        },
      ),
    );
  });

  it("blocks a save that picks no team", async () => {
    renderDialog({ config: null, enableOnSave: true });

    await userEvent.click(screen.getByText("Only the teams I pick"));

    expect(
      screen.getByText("Pick at least one team, or read all teams."),
    ).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: "Turn on Linear" }),
    );
    expect(mocks.createSignalSourceConfig).not.toHaveBeenCalled();
  });

  it("says how to recover when Linear is not connected", async () => {
    mocks.teams = [];
    mocks.status = "missing";
    renderDialog({ config: null, enableOnSave: true });

    await userEvent.click(screen.getByText("Only the teams I pick"));

    expect(screen.getByText(/Reconnect Linear/)).toBeTruthy();
  });
});
