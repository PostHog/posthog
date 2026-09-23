import { describe, expect, it } from "vitest";
import { withBlockCapabilities } from "./blockProject";

describe("withBlockCapabilities", () => {
  it("allows the insights that Insight blocks show and keeps the ones already allowed", () => {
    const files = {
      "src/canvas.tsx":
        '<Insight blockId="a" shortId="Abc123" />\n<Insight\n  blockId="b"\n  title="Signups"\n  shortId="Xyz789"\n/>\n<Insight blockId="c" />',
    };
    const capabilities = withBlockCapabilities(
      { posthog: { insights: ["Old111", "Abc123"] } },
      files,
    );
    expect(capabilities.posthog?.insights).toEqual([
      "Old111",
      "Abc123",
      "Xyz789",
    ]);
    expect(capabilities.posthog?.inlineQueries).toBe(true);
  });
});
