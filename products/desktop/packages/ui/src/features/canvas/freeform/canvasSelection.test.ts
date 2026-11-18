import type { CanvasTextSelection } from "@posthog/core/canvas/freeformSchemas";
import { describe, expect, it } from "vitest";
import { translateCanvasTextSelection } from "./canvasSelection";

const selection = {
  quote: "Hot stuff",
  prefix: "",
  suffix: "",
  start: 0,
  end: 9,
  rect: { top: 10, right: 60, bottom: 30, left: 20 },
} as CanvasTextSelection;

describe("translateCanvasTextSelection", () => {
  it("bounds the selection by the host's frame, not by anything the canvas sends", () => {
    const fromCanvas = {
      ...selection,
      frame: { top: 0, left: 0, right: 5_000, bottom: 5_000 },
    } as CanvasTextSelection;

    expect(
      translateCanvasTextSelection(fromCanvas, {
        top: 100,
        left: 200,
        right: 700,
        bottom: 600,
      }),
    ).toMatchObject({
      rect: { top: 110, right: 260, bottom: 130, left: 220 },
      frame: { top: 100, left: 200, right: 700, bottom: 600 },
    });
  });
});
