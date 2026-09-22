import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  canvasId: "canvas-1" as string | undefined,
  markCanvasViewed: vi.fn(),
}));

vi.mock("@posthog/ui/features/canvas/components/WebsiteDashboard", () => ({
  WebsiteDashboard: ({ dashboardId }: { dashboardId: string }) => (
    <div>{dashboardId}</div>
  ),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useSelectedCanvasId", () => ({
  useSelectedCanvasId: () => mocks.canvasId,
}));
vi.mock("@posthog/ui/features/canvas/stores/canvasViewedStore", () => ({
  useCanvasViewedStore: (
    selector: (state: {
      markCanvasViewed: typeof mocks.markCanvasViewed;
    }) => typeof mocks.markCanvasViewed,
  ) => selector({ markCanvasViewed: mocks.markCanvasViewed }),
}));

import { CanvasesRoute } from "./CanvasesRoute";

describe("CanvasesRoute", () => {
  beforeEach(() => {
    mocks.canvasId = "canvas-1";
    mocks.markCanvasViewed.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("records the selected canvas as viewed", () => {
    vi.spyOn(Date, "now").mockReturnValue(1234);

    render(<CanvasesRoute />);

    expect(mocks.markCanvasViewed).toHaveBeenCalledWith("canvas-1", 1234);
  });
});
