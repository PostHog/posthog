import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MissionControlOverlay } from "./MissionControlOverlay";
import { useMissionControlStore } from "./missionControlStore";

describe("MissionControlOverlay", () => {
  beforeEach(() => {
    useMissionControlStore.setState({ active: false });
  });

  afterEach(() => {
    document.getElementById("portal-container")?.remove();
  });

  it("renders nothing until Mission Control opens", () => {
    render(<MissionControlOverlay />);

    expect(screen.queryByTestId("mission-control-overlay")).toBeNull();
  });

  it("names the app so the window is identifiable at thumbnail size", () => {
    useMissionControlStore.setState({ active: true });
    render(<MissionControlOverlay />);

    expect(screen.getByText("PostHog Desktop")).toBeTruthy();
    expect(screen.getByLabelText("PostHog logo")).toBeTruthy();
  });

  it("never intercepts clicks", () => {
    useMissionControlStore.setState({ active: true });
    render(<MissionControlOverlay />);

    expect(screen.getByTestId("mission-control-overlay").className).toContain(
      "pointer-events-none",
    );
  });

  it("portals into the theme container when one exists", () => {
    // Falling back to document.body lands outside the Radix <Theme> subtree
    // and renders a light panel in dark mode.
    const portal = document.createElement("div");
    portal.id = "portal-container";
    document.body.appendChild(portal);
    useMissionControlStore.setState({ active: true });

    render(<MissionControlOverlay />);

    expect(portal.contains(screen.getByTestId("mission-control-overlay"))).toBe(
      true,
    );
  });
});
