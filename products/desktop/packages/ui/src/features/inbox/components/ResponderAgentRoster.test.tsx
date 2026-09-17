import { cleanup, render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResponderAgentRoster } from "./ResponderAgentRoster";

describe("ResponderAgentRoster", () => {
  afterEach(cleanup);

  const signalTypes = [
    { id: "issue_created", name: "New issue", enabled: true },
    { id: "issue_reopened", name: "Reopened issue", enabled: false },
  ];

  function renderRoster(
    overrides: Partial<Parameters<typeof ResponderAgentRoster>[0]> = {},
  ) {
    return render(
      <ResponderAgentRoster
        value={{ error_tracking: true }}
        onToggle={vi.fn()}
        sourceStates={{
          error_tracking: {
            requiresSetup: false,
            loading: false,
            entities: signalTypes,
          },
          replay_vision: {
            requiresSetup: false,
            loading: false,
            entities: [{ id: "s1", name: "Checkout scanner", enabled: false }],
          },
        }}
        {...overrides}
      />,
    );
  }

  it("lists a source's entities only once its card is expanded", async () => {
    renderRoster();

    expect(screen.queryByText("Reopened issue")).toBeNull();
    expect(screen.getByText("1 of 2 signal types on")).toBeTruthy();

    await userEvent.click(screen.getByText("Error Tracking"));

    expect(screen.getByText("New issue")).toBeTruthy();
    expect(screen.getByText("Reopened issue")).toBeTruthy();
  });

  it("switches one entity rather than the whole source", async () => {
    const onToggle = vi.fn();
    const onToggleEntity = vi.fn();
    renderRoster({ onToggle, onToggleEntity });

    await userEvent.click(screen.getByText("Error Tracking"));
    await userEvent.click(
      screen.getByRole("switch", { name: "Reopened issue" }),
    );

    expect(onToggleEntity).toHaveBeenCalledWith(
      "error_tracking",
      "issue_reopened",
    );
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("gives a source with user-created entities no master switch", () => {
    renderRoster();

    expect(
      screen.queryByRole("switch", { name: "Arm Replay vision" }),
    ).toBeNull();
    expect(
      screen.getByRole("switch", { name: "Arm Error Tracking" }),
    ).toBeTruthy();
  });
});
