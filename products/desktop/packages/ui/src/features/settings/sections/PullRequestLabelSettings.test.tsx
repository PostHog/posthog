import type { SignalTeamConfig } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PullRequestLabelSettings } from "./PullRequestLabelSettings";

function config(overrides: Partial<SignalTeamConfig> = {}): SignalTeamConfig {
  return {
    id: "config-1",
    default_autostart_priority: "P2",
    pull_request_label_enabled: false,
    pull_request_label: null,
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:00Z",
    ...overrides,
  } as SignalTeamConfig;
}

function renderSettings(
  teamConfig: SignalTeamConfig,
  onSave = vi.fn().mockResolvedValue(undefined),
) {
  render(<PullRequestLabelSettings config={teamConfig} onSave={onSave} />);
  return { onSave };
}

describe("PullRequestLabelSettings", () => {
  it("hides the name field while labelling is off", () => {
    renderSettings(config());

    expect(
      screen.getByLabelText("Label self-driving pull requests on GitHub"),
    ).not.toBeChecked();
    expect(
      screen.queryByLabelText("Pull request label name"),
    ).not.toBeInTheDocument();
  });

  it("shows the saved label", () => {
    renderSettings(
      config({
        pull_request_label_enabled: true,
        pull_request_label: "ship-it",
      }),
    );

    expect(screen.getByLabelText("Pull request label name")).toHaveValue(
      "ship-it",
    );
  });

  it("turns labelling on without touching the name", async () => {
    const { onSave } = renderSettings(config());

    await userEvent.click(
      screen.getByLabelText("Label self-driving pull requests on GitHub"),
    );

    expect(onSave).toHaveBeenCalledWith({ pull_request_label_enabled: true });
  });

  it("saves a typed name", async () => {
    const { onSave } = renderSettings(
      config({ pull_request_label_enabled: true }),
    );

    await userEvent.type(
      screen.getByLabelText("Pull request label name"),
      "release-bot",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith({ pull_request_label: "release-bot" });
  });

  it("clears a name back to the server default", async () => {
    const { onSave } = renderSettings(
      config({
        pull_request_label_enabled: true,
        pull_request_label: "ship-it",
      }),
    );

    await userEvent.clear(screen.getByLabelText("Pull request label name"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith({ pull_request_label: null });
  });

  it("keeps the typed name when the save fails", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("nope"));
    renderSettings(
      config({
        pull_request_label_enabled: true,
        pull_request_label: "ship-it",
      }),
      onSave,
    );

    const input = screen.getByLabelText("Pull request label name");
    await userEvent.clear(input);
    await userEvent.type(input, "release-bot");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith({ pull_request_label: "release-bot" });
    expect(input).toHaveValue("release-bot");
  });
});
