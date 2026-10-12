import { describe, expect, it } from "vitest";
import { findTranslator } from "./findTranslator";

describe("findTranslator", () => {
  it("emits a location from the search path and text content from results", () => {
    const output = findTranslator({
      toolCallId: "call-1",
      arguments: { pattern: "*.ts", path: "packages/core/src" },
      resultContent: [
        {
          type: "text",
          text: "packages/core/src/foo.ts\npackages/core/src/bar.ts",
        },
      ],
    });

    expect(output.locations).toEqual([{ path: "packages/core/src" }]);
    expect(output.content).toEqual([
      {
        type: "content",
        content: {
          type: "text",
          text: "packages/core/src/foo.ts\npackages/core/src/bar.ts",
        },
      },
    ]);
  });

  it("omits locations and content when path and resultContent are absent", () => {
    const output = findTranslator({
      toolCallId: "call-2",
      arguments: { pattern: "*.ts" },
    });

    expect(output.locations).toBeUndefined();
    expect(output.content).toBeUndefined();
  });

  it("returns no content when result blocks are all images", () => {
    const output = findTranslator({
      toolCallId: "call-3",
      arguments: { pattern: "*.png", path: "assets" },
      resultContent: [
        { type: "image", data: "base64data", mimeType: "image/png" },
      ],
    });

    expect(output.locations).toEqual([{ path: "assets" }]);
    expect(output.content).toBeUndefined();
  });
});
