import type {
  GridDefinition,
  GridPlacement,
} from "@posthog/core/canvas/gridLayoutSchemas";
import { act, renderHook } from "@testing-library/react";
import type { RefObject } from "react";
import { describe, expect, it, vi } from "vitest";
import { useGridDrag } from "./useGridDrag";

const GRID: GridDefinition = { columns: 6, rowHeight: 96, gap: 8 };
const PLACEMENT: GridPlacement = {
  id: "widget",
  status: "live",
  x: 0,
  y: 0,
  w: 1,
  h: 1,
};

function pointer(clientX: number, clientY: number): React.PointerEvent {
  return {
    button: 0,
    clientX,
    clientY,
    pointerId: 1,
    stopPropagation: vi.fn(),
  } as unknown as React.PointerEvent;
}

describe("useGridDrag", () => {
  it("commits a move when pointer events arrive before React rerenders", () => {
    const onComplete = vi.fn();
    const surface = document.createElement("div");
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width: 600,
    } as DOMRect);
    surface.setPointerCapture = vi.fn();
    const surfaceRef = { current: surface } as RefObject<HTMLDivElement | null>;
    const { result } = renderHook(() =>
      useGridDrag({
        surfaceRef,
        grid: GRID,
        interactive: true,
        onComplete,
      }),
    );

    act(() => {
      result.current.startMove(PLACEMENT)(pointer(50, 50));
      result.current.onPointerMove(pointer(250, 50));
      result.current.onPointerUp();
    });

    expect(onComplete).toHaveBeenCalledWith({
      kind: "move",
      placementId: "widget",
      origin: PLACEMENT,
      rect: { x: 2, y: 0, w: 1, h: 1 },
    });
  });
});
