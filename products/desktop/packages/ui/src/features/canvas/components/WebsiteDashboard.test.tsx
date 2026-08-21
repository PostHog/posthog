import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Hoisted so the module factory can read it and each case can steer what the record query
// resolved to.
const record = vi.hoisted(() => ({
  current: {
    dashboard: undefined as unknown,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null as { message: string } | null,
    refetch: vi.fn(),
  },
}));

vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useDashboard: () => record.current,
}));
// The two canvas views mount iframes, chat panels and grid layout; this suite only cares about
// which of them the branch picks.
vi.mock("@posthog/ui/features/canvas/freeform/FreeformCanvasView", () => ({
  FreeformCanvasView: () => <div data-testid="freeform-view" />,
}));
vi.mock("@posthog/ui/features/canvas/grid/GridCanvasView", () => ({
  GridCanvasView: () => <div data-testid="grid-view" />,
}));
vi.mock("@posthog/ui/features/canvas/stores/dashboardEditStore", () => ({
  useIsDashboardEditing: () => false,
}));
vi.mock("@posthog/ui/router/routeSkeletons", () => ({
  CanvasSkeleton: () => <div data-testid="canvas-skeleton" />,
}));
vi.mock("@posthog/ui/features/canvas/components/CanvasNotFound", () => ({
  CanvasNotFound: () => <div data-testid="canvas-not-found" />,
}));
vi.mock("@posthog/ui/features/canvas/components/CanvasLoadFailed", () => ({
  CanvasLoadFailed: () => <div data-testid="canvas-load-failed" />,
}));

import { WebsiteDashboard } from "@posthog/ui/features/canvas/components/WebsiteDashboard";

describe("WebsiteDashboard", () => {
  beforeEach(() => {
    record.current = {
      dashboard: undefined,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
  });

  // The null row is the regression this file exists for: a canvas the signed-in project does
  // not have used to fall through to the freeform view, which renders its own empty state and
  // reads as a real, empty canvas.
  it.each([
    ["still resolving", { isLoading: true }, "canvas-skeleton"],
    [
      "failed to load",
      { isError: true, error: { message: "boom" } },
      "canvas-load-failed",
    ],
    ["absent from this project", { dashboard: null }, "canvas-not-found"],
    ["a grid canvas", { dashboard: { kind: "grid" } }, "grid-view"],
    ["a freeform canvas", { dashboard: { kind: "freeform" } }, "freeform-view"],
  ])("renders %s as %s", (_label, state, expectedTestId) => {
    record.current = { ...record.current, ...state };

    render(<WebsiteDashboard dashboardId="dash-1" channelId="chan-1" />);

    expect(screen.getByTestId(expectedTestId)).toBeInTheDocument();
  });

  it("does not render a canvas view when the record is absent", () => {
    record.current = { ...record.current, dashboard: null };

    render(<WebsiteDashboard dashboardId="dash-1" channelId="chan-1" />);

    expect(screen.queryByTestId("freeform-view")).not.toBeInTheDocument();
    expect(screen.queryByTestId("grid-view")).not.toBeInTheDocument();
  });
});
