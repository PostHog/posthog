import { describe, expect, it } from "vitest";
import { canvasToHostMessageSchema } from "./freeformSchemas";

describe("canvasToHostMessageSchema open-external", () => {
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
});
