import { readFile } from "node:fs/promises";
import { createSketchpadCache, sketchpadCacheSchema } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import {
  sketchpadAddFragmentTool,
  sketchpadGetFragmentTool,
  sketchpadRemoveFragmentTool,
  sketchpadSetStateTool,
  sketchpadUpdateFragmentTool,
} from "./sketchpad";

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
  snapshot: { schemaVersion: 1 as const, fragments, state: {} },
};

describe("sketchpad tools", () => {
  it.each([
    [
      sketchpadAddFragmentTool,
      { id: "one", code: "export default () => null", x: Infinity },
    ],
    [
      sketchpadAddFragmentTool,
      { id: "one", code: 'import x from "unlisted"; export default () => x' },
    ],
    [sketchpadUpdateFragmentTool, { id: "one", patch: {} }],
    [sketchpadRemoveFragmentTool, { id: "" }],
    [sketchpadSetStateTool, { key: "", value: 1 }],
    [sketchpadSetStateTool, { key: "large", value: "x".repeat(70_000) }],
  ])("rejects invalid edits before reporting success", async (tool, args) => {
    const result = await tool.handler(
      { cwd: "/tmp", sketchpadId: "board" },
      args,
    );
    expect(result.isError).toBe(true);
  });

  it.each([
    [
      sketchpadAddFragmentTool,
      { id: "Date Range", code: "export default () => null" },
    ],
    [sketchpadUpdateFragmentTool, { id: "Date Range", patch: { x: 10 } }],
    [sketchpadRemoveFragmentTool, { id: "Date Range" }],
  ])(
    "reports the normalized fragment id as a queued edit",
    async (tool, args) => {
      const result = await tool.handler(
        { cwd: "/tmp", sketchpadId: "board" },
        args,
      );
      expect(result.isError).toBeUndefined();
      expect(result.content[0].text).toContain("date-range");
      expect(result.content[0].text).toContain("Queued");
    },
  );

  it.each([undefined, "", "board"])(
    "enables tools only for a nonempty sketchpad id",
    (sketchpadId) => {
      expect(
        sketchpadAddFragmentTool.isEnabled({ cwd: "/tmp" }, { sketchpadId }),
      ).toBe(Boolean(sketchpadId));
    },
  );

  it("returns complete cached fragments to agents", async () => {
    const cache = sketchpadCacheSchema.parse(createSketchpadCache(input));
    vi.mocked(readFile).mockResolvedValue(JSON.stringify(cache));
    for (const fragment of fragments) {
      const result = await sketchpadGetFragmentTool.handler(
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
      const result = await sketchpadGetFragmentTool.handler(
        { cwd: "/tmp", sketchpadId: "board" },
        { id: fragments[0].id },
      );
      expect(result.isError).toBe(true);
    },
  );
});
