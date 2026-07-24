import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ModeSelector } from "./ModeSelector";

function modeOption(currentValue = "plan"): SessionConfigOption {
  return {
    id: "mode",
    name: "Mode",
    type: "select",
    category: "mode",
    currentValue,
    options: [
      { value: "plan", name: "Plan" },
      { value: "auto", name: "Auto" },
    ],
  } as SessionConfigOption;
}

describe("ModeSelector", () => {
  it("shows the current mode on the trigger", () => {
    render(
      <ModeSelector
        modeOption={modeOption("plan")}
        onChange={vi.fn()}
        allowBypassPermissions={false}
      />,
    );
    expect(screen.getByRole("button", { name: "Mode" })).toHaveTextContent(
      "Plan",
    );
  });

  it("shows Canvas on the trigger while canvas mode is armed", () => {
    render(
      <ModeSelector
        modeOption={modeOption("plan")}
        onChange={vi.fn()}
        allowBypassPermissions={false}
        canvas={{ active: true, onToggle: vi.fn() }}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Mode" });
    expect(trigger).toHaveTextContent("Canvas");
    expect(trigger).not.toHaveTextContent("Plan");
  });
});
