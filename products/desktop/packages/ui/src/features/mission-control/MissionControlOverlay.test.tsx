import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MissionControlOverlay } from "./MissionControlOverlay";
import { useMissionControlStore } from "./missionControlStore";

describe("MissionControlOverlay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useMissionControlStore.setState({ active: false });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
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

  it.each([
    { dev: true, expected: true },
    { dev: false, expected: false },
  ])(
    "shows the development badge only in a dev build (DEV=$dev)",
    ({ dev, expected }) => {
      vi.stubEnv("DEV", dev);
      useMissionControlStore.setState({ active: true });
      render(<MissionControlOverlay />);

      expect(screen.queryByText("Development") !== null).toBe(expected);
    },
  );

  it("never intercepts clicks", () => {
    useMissionControlStore.setState({ active: true });
    render(<MissionControlOverlay />);

    expect(screen.getByTestId("mission-control-overlay").className).toContain(
      "pointer-events-none",
    );
  });

  it("fades in and stays mounted while fading out", () => {
    useMissionControlStore.setState({ active: true });
    render(<MissionControlOverlay />);

    expect(screen.getByTestId("mission-control-overlay")).toHaveClass(
      "opacity-0",
    );
    act(() => vi.runAllTimers());
    expect(screen.getByTestId("mission-control-overlay")).toHaveClass(
      "opacity-100",
    );

    act(() => useMissionControlStore.setState({ active: false }));
    expect(screen.getByTestId("mission-control-overlay")).toHaveClass(
      "opacity-0",
    );

    act(() => vi.advanceTimersByTime(150));
    expect(screen.queryByTestId("mission-control-overlay")).toBeNull();
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
