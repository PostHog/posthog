import { describe, expect, it } from "vitest";
import {
  computeContainerDimensions,
  FULLSCREEN_HEADER_HEIGHT,
  FULLSCREEN_PADDING,
  INLINE_MAX_HEIGHT,
  toCallToolResult,
} from "./mcp-app-host-utils";

describe("computeContainerDimensions", () => {
  it("returns inline dimensions with maxHeight", () => {
    const result = computeContainerDimensions("inline", 500);
    expect(result).toEqual({
      width: 500,
      maxHeight: INLINE_MAX_HEIGHT,
    });
    expect(result.height).toBeUndefined();
  });

  it("uses provided inlineWidth for inline mode", () => {
    expect(computeContainerDimensions("inline", 800).width).toBe(800);
    expect(computeContainerDimensions("inline", 320).width).toBe(320);
  });

  it("returns fullscreen dimensions based on viewport", () => {
    const result = computeContainerDimensions("fullscreen", 500, 1920, 1080);
    expect(result).toEqual({
      width: 1920 - FULLSCREEN_PADDING,
      height: 1080 - FULLSCREEN_HEADER_HEIGHT - FULLSCREEN_PADDING,
    });
    expect(result.maxHeight).toBeUndefined();
  });

  it("clamps fullscreen dimensions to zero for tiny viewports", () => {
    const result = computeContainerDimensions("fullscreen", 500, 10, 10);
    expect(result.width).toBe(0);
    expect(result.height).toBe(0);
  });

  it("ignores inlineWidth in fullscreen mode", () => {
    const a = computeContainerDimensions("fullscreen", 100, 1920, 1080);
    const b = computeContainerDimensions("fullscreen", 999, 1920, 1080);
    expect(a.width).toBe(b.width);
    expect(a.height).toBe(b.height);
  });
});

describe("toCallToolResult", () => {
  it("passes through a well-formed CallToolResult", () => {
    const result = {
      content: [{ type: "text" as const, text: "hello" }],
      isError: false,
    };
    expect(toCallToolResult(result)).toBe(result);
  });

  it("passes through a result with structuredContent", () => {
    const result = {
      content: [],
      structuredContent: { key: "value" },
    };
    expect(toCallToolResult(result)).toBe(result);
  });

  it("wraps a bare string into a text content block", () => {
    expect(toCallToolResult("hello")).toEqual({
      content: [{ type: "text", text: "hello" }],
    });
  });

  it("wraps null into an empty text content block", () => {
    expect(toCallToolResult(null)).toEqual({
      content: [{ type: "text", text: "" }],
    });
  });

  it("wraps undefined into an empty text content block", () => {
    expect(toCallToolResult(undefined)).toEqual({
      content: [{ type: "text", text: "" }],
    });
  });

  it("JSON-stringifies non-string objects without content", () => {
    expect(toCallToolResult({ foo: "bar" })).toEqual({
      content: [{ type: "text", text: '{"foo":"bar"}' }],
    });
  });

  it("normalizes content that is a string instead of an array", () => {
    const result = toCallToolResult({
      content: "plain text result",
      isError: false,
    });
    expect(result).toEqual({
      content: [{ type: "text", text: "plain text result" }],
      isError: false,
    });
  });

  it("normalizes content that is a non-array non-string", () => {
    const result = toCallToolResult({
      content: 42,
      isError: true,
    });
    expect(result).toEqual({
      content: [{ type: "text", text: "42" }],
      isError: true,
    });
  });

  it("preserves structuredContent when normalizing string content", () => {
    const structured = { type: "chart", data: [1, 2, 3] };
    const result = toCallToolResult({
      content: "fallback text",
      structuredContent: structured,
      isError: false,
    });
    expect(result).toEqual({
      content: [{ type: "text", text: "fallback text" }],
      structuredContent: structured,
      isError: false,
    });
  });

  it("preserves _meta when normalizing string content", () => {
    const result = toCallToolResult({
      content: "text",
      _meta: { requestId: "abc" },
      structuredContent: { key: "val" },
    });
    expect(result).toEqual({
      content: [{ type: "text", text: "text" }],
      _meta: { requestId: "abc" },
      structuredContent: { key: "val" },
    });
  });
});
