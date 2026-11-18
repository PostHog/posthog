import { describe, expect, it } from "vitest";
import { BLOCK_RUNTIME_PATH } from "./blockDefinitions";
import { canvasCapabilities } from "./blockProject";

describe("canvasCapabilities", () => {
  it("allows the insights that Insight blocks show and keeps the ones already allowed", () => {
    const files = {
      [BLOCK_RUNTIME_PATH]: "",
      "src/canvas.tsx":
        '<Insight blockId="a" shortId="Abc123" />\n<Insight\n  blockId="b"\n  title="Signups"\n  shortId="Xyz789"\n/>\n<Insight blockId="c" />',
    };
    const capabilities = canvasCapabilities(
      { posthog: { insights: ["Old111", "Abc123"] } },
      files,
    );
    expect(capabilities?.posthog?.insights).toEqual([
      "Old111",
      "Abc123",
      "Xyz789",
    ]);
    expect(capabilities?.posthog?.inlineQueries).toBe(true);
  });
});
