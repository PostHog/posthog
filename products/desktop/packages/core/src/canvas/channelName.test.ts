import { describe, expect, it } from "vitest";
import { validateChannelName } from "./channelName";

describe("validateChannelName", () => {
  it.each([
    "mobile",
    "web-analytics",
    "team-1",
    "a",
    "123",
    "a-b-c",
    "  mobile  ", // surrounding whitespace is trimmed before validating
  ])("returns null for valid name %j", (name) => {
    expect(validateChannelName(name)).toBeNull();
  });

  it.each(["", "   "])("returns null for empty/blank name %j", (name) => {
    expect(validateChannelName(name)).toBeNull();
  });

  it.each(["Mobile", "my channel", "team_1", "café", "a.b", "a/b", "emoji🚀"])(
    "returns an error for invalid name %j",
    (name) => {
      expect(validateChannelName(name)).toBe(
        "Use only lowercase letters, numbers, and hyphens.",
      );
    },
  );
});
