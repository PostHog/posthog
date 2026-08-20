import { describe, expect, it } from "vitest";
import {
  canvasToHostMessageSchema,
  hostToCanvasMessageSchema,
  limitCanvasCommentHighlights,
} from "./freeformSchemas";

describe("canvasToHostMessageSchema", () => {
  const message = (url: string) => ({
    channel: "posthog-canvas",
    type: "open-external",
    url,
  });

  it.each([
    "https://posthog.com/docs",
    "https://us.posthog.com/project/2",
    "https://app.posthog.com",
  ])("accepts %s", (url) => {
    expect(canvasToHostMessageSchema.safeParse(message(url)).success).toBe(
      true,
    );
  });

  it.each([
    "https://example.com",
    "http://posthog.com",
    "https://posthog.com.evil.com",
    "mailto:hi@posthog.com",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "/relative/path",
    "",
  ])("rejects %s", (url) => {
    expect(canvasToHostMessageSchema.safeParse(message(url)).success).toBe(
      false,
    );
  });

  // The bridge dispatches on `method` after this schema parse, so a method
  // missing from the enum is a bridge verb the host silently drops.
  it.each(["stateGet", "stateSet", "stateList", "actionInvoke"])(
    "accepts %s data requests",
    (method) => {
      expect(
        canvasToHostMessageSchema.safeParse({
          channel: "posthog-canvas",
          type: "data-request",
          id: "request-1",
          method,
          payload: {},
        }).success,
      ).toBe(true);
    },
  );

  it("accepts a bounded text selection and rejects oversized selected text", () => {
    const selection = {
      channel: "posthog-canvas",
      type: "text-selection",
      selection: {
        quote: "selected text",
        prefix: "before ",
        suffix: " after",
        start: 7,
        end: 20,
        rect: { top: 10, right: 80, bottom: 30, left: 20 },
      },
    };

    expect(canvasToHostMessageSchema.safeParse(selection).success).toBe(true);
    expect(
      canvasToHostMessageSchema.safeParse({
        ...selection,
        selection: { ...selection.selection, quote: "x".repeat(10_001) },
      }).success,
    ).toBe(false);
  });

  it("accepts an explicit selection-cleared event", () => {
    expect(
      canvasToHostMessageSchema.safeParse({
        channel: "posthog-canvas",
        type: "text-selection-cleared",
      }).success,
    ).toBe(true);
  });

  it("accepts a bounded comment activation", () => {
    expect(
      canvasToHostMessageSchema.safeParse({
        channel: "posthog-canvas",
        type: "comment-activate",
        id: "comment-1",
      }).success,
    ).toBe(true);
  });

  it("accepts bounded comment highlights", () => {
    expect(
      hostToCanvasMessageSchema.safeParse({
        channel: "posthog-canvas",
        type: "set-comment-highlights",
        highlights: [
          {
            id: "comment-1",
            active: false,
            anchor: {
              quote: "selected text",
              prefix: "before ",
              suffix: " after",
              start: 7,
              end: 20,
            },
          },
        ],
      }).success,
    ).toBe(true);
  });

  it.each([
    {
      name: "protocol item limit",
      count: 501,
      quote: "x",
      expected: 500,
    },
    {
      name: "aggregate anchor text budget",
      count: 11,
      quote: "x".repeat(10_000),
      expected: 10,
    },
  ])("limits highlights by $name", ({ count, quote, expected }) => {
    const highlights = Array.from({ length: count }, (_, index) => ({
      id: `comment-${index}`,
      active: false,
      anchor: {
        quote,
        prefix: "",
        suffix: "",
        start: 0,
        end: quote.length,
      },
    }));

    expect(limitCanvasCommentHighlights(highlights)).toHaveLength(expected);
  });

  it("accepts a host request to clear native text selection", () => {
    expect(
      hostToCanvasMessageSchema.parse({
        channel: "posthog-canvas",
        type: "clear-text-selection",
      }),
    ).toEqual({
      channel: "posthog-canvas",
      type: "clear-text-selection",
    });
  });
});
