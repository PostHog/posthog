import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  dashboards: [] as DashboardRecord[],
  navigate: vi.fn(),
  track: vi.fn(),
  viewedState: {
    lastViewedAtByCanvasId: {} as Record<string, number>,
    markCanvasViewed: vi.fn(),
  },
}));

vi.mock("@posthog/ui/features/auth/useMeQuery", () => ({
  useMeQuery: () => ({ data: null }),
}));
vi.mock("@posthog/di/react", async () => {
  const { CanvasListService } = await import(
    "@posthog/core/canvas/canvasListService"
  );
  return { useService: () => new CanvasListService() };
});
vi.mock("@posthog/ui/features/canvas/components/CanvasFilterMenu", () => ({
  CanvasFilterMenu: () => <button type="button">Filter canvases</button>,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [], isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useAllCanvases: () => ({ dashboards: mocks.dashboards, isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useSelectedCanvasId", () => ({
  useSelectedCanvasId: () => undefined,
}));
vi.mock("@posthog/ui/features/canvas/stores/canvasViewedStore", () => {
  const useCanvasViewedStore = Object.assign(
    (selector: (state: typeof mocks.viewedState) => unknown): unknown =>
      selector(mocks.viewedState),
    {
      getState: () => mocks.viewedState,
      persist: {
        hasHydrated: () => true,
        onFinishHydration: () => () => {},
      },
    },
  );
  return { useCanvasViewedStore };
});
vi.mock("@posthog/ui/shell/analytics", () => ({ track: mocks.track }));
vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useNavigate: () => mocks.navigate,
}));

import { CanvasesPane } from "./CanvasesPane";

function canvas(id: string, name: string, updatedAt: number): DashboardRecord {
  return {
    id,
    channelId: "space-1",
    name,
    kind: "freeform",
    description: "",
    templateId: "freeform",
    context: "",
    createdAt: updatedAt,
    updatedAt,
  };
}

describe("CanvasesPane", () => {
  beforeEach(() => {
    mocks.dashboards = [
      canvas("canvas-first", "First canvas", 2),
      canvas("canvas-second", "Second canvas", 1),
    ];
    mocks.navigate.mockReset();
    mocks.track.mockReset();
    mocks.viewedState.markCanvasViewed.mockReset();
    mocks.viewedState.lastViewedAtByCanvasId = {};
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("groups canvases by date by default", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 7, 20, 12));
    mocks.dashboards = [
      canvas(
        "canvas-today",
        "Today canvas",
        new Date(2026, 7, 20, 8).getTime(),
      ),
      canvas(
        "canvas-yesterday",
        "Yesterday canvas",
        new Date(2026, 7, 19, 8).getTime(),
      ),
    ];

    render(<CanvasesPane />);

    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Yesterday")).toBeInTheDocument();
  });

  it("moves through canvases from the search input and opens the highlighted row", async () => {
    const user = userEvent.setup();
    render(<CanvasesPane />);

    expect(screen.getAllByRole("option")).toHaveLength(2);
    await user.click(screen.getByLabelText("Search canvases"));
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}{Enter}");

    expect(mocks.navigate).toHaveBeenCalledWith({
      to: "/canvases",
      search: { canvas: "canvas-first" },
    });
  });
});
