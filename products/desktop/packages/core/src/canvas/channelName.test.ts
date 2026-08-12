import { describe, expect, it } from "vitest";
import {
  normalizeChannelName,
  normalizeChannelNameInput,
  validateChannelName,
} from "./channelName";

describe("normalizeChannelName", () => {
  it.each([
    ["My New Space", "my-new-space"],
    ["  Product   Analytics  ", "product-analytics"],
    ["Mobile_App.v2", "mobile-app-v2"],
    ["already-valid", "already-valid"],
    ["café 🚀", "caf"],
  ])("normalizes %j to %j", (name, expected) => {
    expect(normalizeChannelName(name)).toBe(expected);
  });

  it("preserves separators while a multi-word name is typed", () => {
    const normalized = [..."My New Space"].reduce(
      (name, character) => normalizeChannelNameInput(name + character),
      "",
    );

    expect(normalized).toBe("my-new-space");
  });
});

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
