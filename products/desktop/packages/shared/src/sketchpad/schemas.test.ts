import { expect, it } from "vitest";
import {
  createSketchpadCache,
  expandSketchpadCache,
  sketchpadFragmentSchema,
} from "./schemas";

it("deduplicates cache sources and expands complete fragments", () => {
  const fragments = ["first source", "second source", "first source"].map(
    (code, index) =>
      sketchpadFragmentSchema.parse({
        id: `fragment-${index}`,
        x: index,
        y: 0,
        w: 360,
        h: 240,
        code,
      }),
  );
  const input = {
    sketchpadId: "board",
    name: "Sketchpad",
    headSeq: 1,
    snapshot: { schemaVersion: 1 as const, fragments, state: {} },
  };
  const cache = createSketchpadCache(input);
  expect(cache.sources).toEqual(["first source", "second source"]);
  expect(cache.snapshot.fragments.map(({ source }) => source)).toEqual([
    0, 1, 0,
  ]);
  expect(expandSketchpadCache(cache)).toEqual(input);
});
