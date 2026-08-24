import { describe, expect, it } from "vitest";
import { lsTranslator } from "./lsTranslator";

describe("lsTranslator", () => {
  it("returns a location for the listed path and text content from the result", () => {
    const output = lsTranslator({
      toolCallId: "call-1",
      arguments: { path: "src/features" },
      resultContent: [{ type: "text", text: "sessions/\ntools/" }],
    });

    expect(output.locations).toEqual([{ path: "src/features" }]);
    expect(output.content).toEqual([
      { type: "content", content: { type: "text", text: "sessions/\ntools/" } },
    ]);
  });

  it("omits locations when no path is given and content when result is empty", () => {
    const output = lsTranslator({
      toolCallId: "call-2",
      arguments: {},
      resultContent: [],
    });

    expect(output.locations).toBeUndefined();
    expect(output.content).toBeUndefined();
  });

  it("still surfaces content on an error result", () => {
    const output = lsTranslator({
      toolCallId: "call-3",
      arguments: { path: "missing-dir" },
      resultContent: [{ type: "text", text: "ENOENT: no such directory" }],
      isError: true,
    });

    expect(output.locations).toEqual([{ path: "missing-dir" }]);
    expect(output.content).toEqual([
      {
        type: "content",
        content: { type: "text", text: "ENOENT: no such directory" },
      },
    ]);
  });

  it("ignores image content blocks", () => {
    const output = lsTranslator({
      toolCallId: "call-4",
      arguments: { path: "src" },
      resultContent: [
        { type: "image", data: "base64data", mimeType: "image/png" },
      ],
    });

    expect(output.content).toBeUndefined();
  });
});
