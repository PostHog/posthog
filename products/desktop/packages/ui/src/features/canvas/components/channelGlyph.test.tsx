import { HashIcon, LockSimpleIcon } from "@phosphor-icons/react";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { channelGlyph, isPrivateChannel } from "./channelGlyph";

describe("isPrivateChannel", () => {
  it.each([
    ["me", true],
    ["  Me  ", true],
    ["ME", true],
    ["code", false],
    ["posthog-feedback", false],
    // Not a prefix match: only the personal channel itself is private.
    ["meeting-notes", false],
    ["team-me", false],
    [undefined, false],
    ["", false],
  ])("%s -> %s", (name, expected) => {
    expect(isPrivateChannel(name)).toBe(expected);
  });
});

describe("channelGlyph", () => {
  it.each([
    ["channel", false, HashIcon],
    ["private space", true, LockSimpleIcon],
  ])("renders the %s glyph", (_, space, expectedIcon) => {
    const name = expectedIcon === LockSimpleIcon ? "me" : "engineering";
    const glyph = channelGlyph(name, { space }) as ReactElement;

    expect(glyph.type).toBe(expectedIcon);
  });

  // A shared space carries no mark at all: the cube said nothing the name
  // didn't, and only the private one is worth calling out.
  it("gives a shared space no glyph", () => {
    expect(channelGlyph("engineering", { space: true })).toBeNull();
  });
});
