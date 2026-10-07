import { describe, expect, it } from "vitest";
import { grepTranslator } from "./grepTranslator";

describe("grepTranslator", () => {
  it("returns locations and text content on success", () => {
    const result = grepTranslator({
      toolCallId: "call-1",
      arguments: { pattern: "foo", path: "src" },
      resultContent: [
        { type: "text", text: "src/a.ts:1:foo\nsrc/b.ts:2:foo bar" },
      ],
      details: undefined,
      isError: false,
    });

    expect(result.locations).toEqual([{ path: "src" }]);
    expect(result.content).toEqual([
      {
        type: "content",
        content: { type: "text", text: "src/a.ts:1:foo\nsrc/b.ts:2:foo bar" },
      },
    ]);
  });

  it("appends truncation notes and omits locations when path is missing", () => {
    const result = grepTranslator({
      toolCallId: "call-2",
      arguments: { pattern: "foo" },
      resultContent: [{ type: "text", text: "match" }],
      details: { matchLimitReached: 100, linesTruncated: true },
      isError: false,
    });

    expect(result.locations).toBeUndefined();
    expect(result.content).toEqual([
      { type: "content", content: { type: "text", text: "match" } },
      {
        type: "content",
        content: {
          type: "text",
          text: "Match limit reached at 100 matches. Some lines were truncated.",
        },
      },
    ]);
  });

  it("returns undefined content and locations when there is nothing to report", () => {
    const result = grepTranslator({
      toolCallId: "call-3",
      arguments: { pattern: "foo" },
      resultContent: [],
      details: undefined,
      isError: true,
    });

    expect(result.locations).toBeUndefined();
    expect(result.content).toBeUndefined();
  });
});
