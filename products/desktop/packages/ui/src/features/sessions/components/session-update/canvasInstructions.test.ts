import { describe, expect, it } from "vitest";
import {
  extractCanvasInstructions,
  hasCanvasInstructions,
} from "./canvasInstructions";

describe("extractCanvasInstructions", () => {
  it("returns null when there is no canvas-instructions element", () => {
    expect(extractCanvasInstructions("just a normal prompt")).toBeNull();
    expect(hasCanvasInstructions("just a normal prompt")).toBe(false);
  });

  it("extracts the body and strips the element from the text", () => {
    const content =
      "What the user wants:\nadd a retention chart\n\n<canvas_generation_instructions>\nauthoring contract here\n</canvas_generation_instructions>";
    const result = extractCanvasInstructions(content);
    expect(result).not.toBeNull();
    expect(result?.body).toBe("authoring contract here");
    expect(result?.stripped).toBe(
      "What the user wants:\nadd a retention chart",
    );
    expect(hasCanvasInstructions(content)).toBe(true);
  });

  it("strips the element even when it is the only content", () => {
    const result = extractCanvasInstructions(
      "<canvas_generation_instructions>\nbody\n</canvas_generation_instructions>",
    );
    expect(result?.body).toBe("body");
    expect(result?.stripped).toBe("");
  });
});
