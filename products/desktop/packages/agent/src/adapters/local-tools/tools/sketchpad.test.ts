import { readFile } from "node:fs/promises";
import { createSketchpadCache, sketchpadCacheSchema } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { canvasGetFragmentTool } from "./sketchpad";

vi.mock("node:fs/promises", () => ({ readFile: vi.fn() }));

const fragments = ["first source", "second source", "first source"].map(
  (code, index) => ({
    id: `fragment-${index}`,
    x: index,
    y: 0,
    w: 360,
    h: 240,
    z: index,
    codeVersion: 1,
    surface: "card" as const,
    hidden: false,
    code,
  }),
);
const input = {
  sketchpadId: "board",
  name: "Sketchpad",
  headSeq: 1,
  historyStartSeq: 1,
  historySnapshot: { schemaVersion: 1 as const, fragments: [], state: {} },
  snapshot: { schemaVersion: 1 as const, fragments, state: {} },
};

describe("sketchpad cache", () => {
  it("stores each source once and returns complete fragments to agents", async () => {
    const cache = sketchpadCacheSchema.parse(createSketchpadCache(input));
    expect(cache.sources).toEqual(["first source", "second source"]);
    expect(cache.snapshot.fragments.map(({ source }) => source)).toEqual([
      0, 1, 0,
    ]);
    vi.mocked(readFile).mockResolvedValue(JSON.stringify(cache));
    for (const fragment of fragments) {
      const result = await canvasGetFragmentTool.handler(
        { cwd: "/tmp", sketchpadId: "board" },
        { id: fragment.id },
      );
      expect(result.isError).toBeUndefined();
      expect(result.content[0].text).toContain(
        JSON.stringify(fragment, null, 2),
      );
    }
  });

  it.each(["missing source", "invalid JSON", "missing file"])(
    "rejects a cache with %s",
    async (failure) => {
      const cache = createSketchpadCache(input);
      cache.sources = [];
      if (failure === "missing file")
        vi.mocked(readFile).mockRejectedValueOnce(new Error("ENOENT"));
      else
        vi.mocked(readFile).mockResolvedValueOnce(
          failure === "invalid JSON" ? "{" : JSON.stringify(cache),
        );
      const result = await canvasGetFragmentTool.handler(
        { cwd: "/tmp", sketchpadId: "board" },
        { id: fragments[0].id },
      );
      expect(result.isError).toBe(true);
    },
  );
});
