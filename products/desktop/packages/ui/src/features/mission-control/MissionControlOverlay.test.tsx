import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { MissionControlOverlay } from "./MissionControlOverlay";
import { useMissionControlStore } from "./missionControlStore";

describe("MissionControlOverlay", () => {
  beforeEach(() => {
    useMissionControlStore.setState({ active: false });
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
});
