import type {
  ReadToolDetails,
  ReadToolInput,
} from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";
import { readTranslator } from "./readTranslator";

describe("readTranslator", () => {
  it("returns the read path as a location and the file text as content", () => {
    const args: ReadToolInput = { path: "src/index.ts" };

    const output = readTranslator({
      toolCallId: "1",
      arguments: args,
      resultContent: [{ type: "text", text: "export const x = 1;" }],
      isError: false,
    });

    expect(output).toEqual({
      locations: [{ path: "src/index.ts" }],
      content: [
        {
          type: "content",
          content: { type: "text", text: "export const x = 1;" },
        },
      ],
    });
  });

  it("appends truncation info when the read result was truncated", () => {
    const args: ReadToolInput = { path: "src/big.ts", offset: 0, limit: 100 };
    const details: ReadToolDetails = {
      truncation: {
        content: "line1\nline2",
        truncated: true,
        truncatedBy: "lines",
        totalLines: 5000,
        totalBytes: 100000,
        outputLines: 100,
        outputBytes: 2000,
        lastLinePartial: false,
        firstLineExceedsLimit: false,
        maxLines: 2000,
        maxBytes: 50000,
      },
    };

    const output = readTranslator({
      toolCallId: "2",
      arguments: args,
      resultContent: [{ type: "text", text: "line1\nline2" }],
      details,
      isError: false,
    });

    expect(output.locations).toEqual([{ path: "src/big.ts" }]);
    expect(output.content).toHaveLength(1);
    const [content] = output.content ?? [];
    expect(content?.type).toBe("content");
    if (content?.type === "content" && content.content.type === "text") {
      expect(content.content.text).toContain("line1\nline2");
      expect(content.content.text).toContain(
        "truncated: showing 100 of 5000 lines",
      );
    }
  });

  it("omits content when the result has no text block, e.g. an error result", () => {
    const args: ReadToolInput = { path: "src/missing.ts" };

    const output = readTranslator({
      toolCallId: "3",
      arguments: args,
      resultContent: undefined,
      isError: true,
    });

    expect(output).toEqual({
      locations: [{ path: "src/missing.ts" }],
      content: undefined,
    });
  });

  it("omits locations when arguments are missing", () => {
    const output = readTranslator({
      toolCallId: "4",
      arguments: undefined,
      resultContent: [{ type: "text", text: "content" }],
      isError: false,
    });

    expect(output.locations).toBeUndefined();
  });
});
