import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasFramePlaceholder } from "./CanvasFramePlaceholder";
import { useCanvasFrameStore } from "./canvasFrameStore";

// The warm-frame host only shows a canvas once its slot has a measured rect
// (`active = ... && !!slot.rect`). The placeholder must populate that rect from
// its own synchronous measure on mount, WITHOUT relying on a later
// ResizeObserver/scroll re-measure — on a settled layout no such re-measure
// fires, so a canvas opened while the app has been running a while (e.g. via a
// deep link) would otherwise stay hidden until a hard refresh. The jsdom
// ResizeObserver stub never fires, so this test reproduces that settled-layout
// condition: if the rect isn't captured synchronously, it never is.

const RECT = { top: 10, left: 20, width: 800, height: 600 };

function resetStore() {
  useCanvasFrameStore.setState({
    slots: [],
    activeDashboardId: null,
    maxWarmFrames: 2,
  });
}

describe("CanvasFramePlaceholder", () => {
  beforeEach(() => {
    resetStore();
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      ...RECT,
      right: RECT.left + RECT.width,
      bottom: RECT.top + RECT.height,
      x: RECT.left,
      y: RECT.top,
      toJSON: () => "",
    } as DOMRect);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    resetStore();
  });

  it("captures the slot rect on mount without a follow-up re-measure", () => {
    render(
      <CanvasFramePlaceholder
        dashboardId="dash-1"
        code="export default () => null"
        onDataRequest={async () => null}
      />,
    );

    const slot = useCanvasFrameStore
      .getState()
      .slots.find((s) => s?.dashboardId === "dash-1");
    expect(slot).toBeTruthy();
    // Pre-fix this is null (the slot is registered in a passive effect that runs
    // after the layout-effect measure, so the first measure is dropped).
    expect(slot?.rect).toEqual(RECT);
    expect(useCanvasFrameStore.getState().activeDashboardId).toBe("dash-1");
  });
});
