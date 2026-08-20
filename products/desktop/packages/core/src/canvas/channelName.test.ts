import { describe, expect, it } from "vitest";
import {
  type ChannelIdentity,
  channelDisplayLabel,
  channelDisplayReference,
  isGeneralChannel,
  isPersonalChannel,
  normalizeChannelName,
  normalizeChannelNameInput,
  validateChannelName,
} from "./channelName";

describe("isPersonalChannel / isGeneralChannel", () => {
  it.each([
    [
      "system_role wins over channel_type/name when present (personal)",
      { system_role: "personal", channel_type: "public", name: "not-me" },
      true,
      false,
    ],
    [
      "system_role wins over channel_type/name when present (general)",
      { system_role: "general", channel_type: "personal", name: "not-general" },
      false,
      true,
    ],
    [
      "null system_role falls back to the legacy checks and matches",
      { system_role: null, channel_type: "personal", name: "me" },
      true,
      false,
    ],
    [
      "null system_role falls back to the legacy checks and matches general",
      { system_role: null, channel_type: "public", name: "general" },
      false,
      true,
    ],
    [
      "neither system_role nor the legacy checks match",
      { system_role: null, channel_type: "public", name: "growth" },
      false,
      false,
    ],
  ] satisfies [string, ChannelIdentity, boolean, boolean][])(
    "%s",
    (_label, channel, expectedPersonal, expectedGeneral) => {
      expect(isPersonalChannel(channel)).toBe(expectedPersonal);
      expect(isGeneralChannel(channel)).toBe(expectedGeneral);
    },
  );
});

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

describe("channelDisplayLabel", () => {
  it.each([
    ["me", undefined, "personal"],
    ["personal", undefined, "personal"],
    ["personal", "personal" as const, "personal"],
    ["personal", "public" as const, "#personal"],
    ["engineering", "public" as const, "#engineering"],
  ])("formats %j (%s) as %j", (name, channelType, expected) => {
    expect(channelDisplayLabel(name, channelType)).toBe(expected);
  });

  it.each([
    ["me", undefined, "your personal space"],
    ["personal", undefined, "your personal space"],
    ["engineering", "public" as const, "#engineering"],
  ])("references %j (%s) as %j", (name, channelType, expected) => {
    expect(channelDisplayReference(name, channelType)).toBe(expected);
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

  // A space taking either of the private space's names wears its lock and sits
  // in its place in the list, which is a space impersonating yours.
  it.each(["personal", "me", "  personal  "])(
    "reserves %j for the private space",
    (name) => {
      expect(validateChannelName(name)).toContain("reserved");
    },
  );
});
