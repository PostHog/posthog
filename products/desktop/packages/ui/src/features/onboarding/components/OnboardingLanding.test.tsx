import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { OnboardingLanding } from "./OnboardingLanding";

describe("OnboardingLanding", () => {
  it.each([
    ["Open spaces", "spaces", "/spaces"],
    ["Open multiplayer", "multiplayer", "/spaces"],
    ["Open self-driving", "self-driving", "/inbox"],
    ["Open canvases", "canvases", "/canvases"],
    ["Open agents", "agents", "/agents"],
    ["Open tasks", "tasks", "/new"],
  ])("requests a new app tab from %s", async (label, destination, href) => {
    const onOpenDestination = vi.fn();
    render(
      <OnboardingLanding
        selfDrivingAvailable
        onOpenDestination={onOpenDestination}
      />,
    );

    await userEvent.click(screen.getByText(label));

    expect(onOpenDestination).toHaveBeenCalledWith(destination, href);
  });

  it("hides self-driving when the destination is unavailable", () => {
    render(
      <OnboardingLanding
        selfDrivingAvailable={false}
        onOpenDestination={vi.fn()}
      />,
    );

    expect(screen.queryByText("Self-driving")).toBeNull();
  });
});
