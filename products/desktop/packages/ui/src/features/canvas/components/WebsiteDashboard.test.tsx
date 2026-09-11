import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

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

  it.each([
    ["still resolving", {}, "canvas-skeleton"],
    [
      "failed to load",
      { isError: true, error: { message: "boom" } },
      "canvas-load-failed",
    ],
    ["absent from this project", { dashboard: null }, "canvas-not-found"],
    [
      "a grid canvas",
      { dashboard: { id: "dash-1", kind: "grid" } },
      "grid-view",
    ],
    [
      "a freeform canvas",
      { dashboard: { id: "dash-1", kind: "freeform" } },
      "freeform-view",
    ],
  ])("renders %s as %s", (_label, state, expectedTestId) => {
    record.current = { ...record.current, ...state };

    render(<WebsiteDashboard dashboardId="dash-1" channelId="chan-1" />);

    expect(screen.getByTestId(expectedTestId)).toBeInTheDocument();
  });
});
