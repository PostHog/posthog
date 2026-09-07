import { describe, expect, it } from "vitest";
import { extractChannelContext, hasChannelContext } from "./channelContext";

describe("extractChannelContext", () => {
  it("returns null when there is no channel-context element", () => {
    expect(extractChannelContext("just a normal prompt")).toBeNull();
    expect(hasChannelContext("just a normal prompt")).toBe(false);
  });

  it("extracts the channel name, body, and strips the element from the text", () => {
    const content =
      'Fix the bug.<channel_context channel="onboarding">\nbackground here\n</channel_context>';
    const result = extractChannelContext(content);
    expect(result).not.toBeNull();
    expect(result?.mention.name).toBe("onboarding");
    expect(result?.mention.body).toBe("background here");
    expect(result?.stripped).toBe("Fix the bug.");
    expect(hasChannelContext(content)).toBe(true);
  });

  it("handles a missing channel attribute", () => {
    const result = extractChannelContext(
      "<channel_context>\nbody\n</channel_context>",
    );
    expect(result?.mention.name).toBeNull();
    expect(result?.mention.body).toBe("body");
    expect(result?.stripped).toBe("");
  });

  it("unescapes the channel name attribute", () => {
    const result = extractChannelContext(
      '<channel_context channel="a &amp; b">x</channel_context>',
    );
    expect(result?.mention.name).toBe("a & b");
  });
});
