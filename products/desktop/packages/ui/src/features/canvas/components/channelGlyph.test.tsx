import { HashIcon, LockSimpleIcon } from "@phosphor-icons/react";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { channelGlyph, isPrivateChannel } from "./channelGlyph";

describe("isPrivateChannel", () => {
  it.each([
    ["personal", true],
    ["  Personal  ", true],
    ["PERSONAL", true],
    // The backend's own name for it, which no longer reaches here: every name
    // a reader sees has been through `channelDisplayName` first.
    ["me", false],
    ["code", false],
    ["posthog-feedback", false],
    // Not a prefix match: only the personal channel itself is private.
    ["personal-notes", false],
    ["team-personal", false],
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
    const name = expectedIcon === LockSimpleIcon ? "personal" : "engineering";
    const glyph = channelGlyph(name, { space }) as ReactElement;

    expect(glyph.type).toBe(expectedIcon);
  });

  // A shared space carries no mark at all: the cube said nothing the name
  // didn't, and only the private one is worth calling out.
  it("gives a shared space no glyph", () => {
    expect(channelGlyph("engineering", { space: true })).toBeNull();
  });

  // The channel type beats the fallback name in both directions so public
  // name collisions stay unmarked and the private space always has a lock.
  it("locks the private space whatever it is called", () => {
    const glyph = channelGlyph("anything", {
      personal: true,
      space: true,
    }) as ReactElement;

    expect(glyph.type).toBe(LockSimpleIcon);
  });

  it("leaves a public space named personal unmarked", () => {
    expect(
      channelGlyph("personal", { personal: false, space: true }),
    ).toBeNull();
  });
});
