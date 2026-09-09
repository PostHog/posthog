import { describe, expect, it, vi } from "vitest";
import {
  CANVAS_DRAG_TYPE,
  readCanvasDragData,
  writeCanvasDragData,
} from "./canvasDrag";

describe("canvas drag data", () => {
  it("writes and reads a canvas id", () => {
    const values = new Map<string, string>();
    const dataTransfer = {
      setData: vi.fn((type: string, value: string) => values.set(type, value)),
      getData: vi.fn((type: string) => values.get(type) ?? ""),
    };

    writeCanvasDragData(dataTransfer, "canvas-1");

    expect(dataTransfer.setData).toHaveBeenCalledWith(
      CANVAS_DRAG_TYPE,
      "canvas-1",
    );
    expect(readCanvasDragData(dataTransfer)).toBe("canvas-1");
  });

  it("returns null when the drag has no canvas", () => {
    expect(readCanvasDragData({ getData: () => "" })).toBeNull();
  });
});
