import { describe, expect, it } from "vitest";
import { hoggiePng } from "./hoggies";

describe("hoggiePng", () => {
  // The slugs whose export name is not a plain camelCase of the file name.
  it.each([
    ["9-9-6"],
    ["996"],
    ["70s-dance"],
    ["x-ray"],
    ["dadd-ai-1"],
    ["wizard-3"],
    ["mr-potato-head-2"],
  ])("resolves %s", (slug) => {
    expect(hoggiePng(slug)).toContain(".png");
  });

  it("gives each hoggie its own image", () => {
    const sources = [
      "business-evolution",
      "organized",
      "research",
      "code-bubble",
    ].map((slug) => hoggiePng(slug));
    expect(new Set(sources).size).toBe(sources.length);
  });

  it("returns undefined for a slug the release does not ship", () => {
    expect(hoggiePng("not-a-hoggie")).toBeUndefined();
  });
});
