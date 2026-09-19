import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CanvasUnavailable } from "./CanvasUnavailable";

const availabilityState = vi.hoisted(() => ({
  current: {
    availability: undefined as string | undefined,
    isLoading: false,
  },
}));

vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useCanvasAvailability: () => availabilityState.current,
}));

function renderWith(current: {
  availability?: string;
  isLoading: boolean;
}): void {
  availabilityState.current = {
    availability: current.availability,
    isLoading: current.isLoading,
  };
  render(<CanvasUnavailable canvasId="canvas-1" />);
}

describe("CanvasUnavailable", () => {
  it("waits for the reason before naming one", () => {
    renderWith({ isLoading: true });

    expect(screen.queryByText("Canvas not found")).toBeNull();
    expect(
      screen.queryByText("You don't have access to this canvas"),
    ).toBeNull();
  });

  it("names the space when the canvas is real but not shared", () => {
    renderWith({ availability: "no_access", isLoading: false });

    expect(
      screen.getByText("You don't have access to this canvas"),
    ).toBeVisible();
    expect(screen.getByText(/has not been shared with you/)).toBeVisible();
  });

  it.each(["missing", undefined])(
    "falls back to not-found for %s",
    (availability) => {
      renderWith({ availability, isLoading: false });

      expect(screen.getByText("Canvas not found")).toBeVisible();
      expect(
        screen.getByText(/different organization or project/),
      ).toBeVisible();
    },
  );
});
