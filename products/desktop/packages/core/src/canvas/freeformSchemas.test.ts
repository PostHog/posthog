import { describe, expect, it } from "vitest";
import { canvasToHostMessageSchema } from "./freeformSchemas";

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
});
