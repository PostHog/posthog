import { describe, expect, it } from "vitest";
import {
  getShortcutsByCategory,
  KEYBOARD_SHORTCUTS,
  SHORTCUTS,
} from "./keyboard-shortcuts";

function idsFor(channelsLayout: boolean): string[] {
  return Object.values(getShortcutsByCategory({ channelsLayout }))
    .flat()
    .map((s) => s.id);
}

describe("getShortcutsByCategory", () => {
  it("advertises channel switching only in the channels layout", () => {
    expect(idsFor(true)).toContain("switch-starred-channel");
    expect(idsFor(false)).not.toContain("switch-starred-channel");
  });

  it.each(["switch-task", "new-tab"])(
    "hides %s in the channels layout, where nothing owns it",
    (id) => {
      expect(idsFor(false)).toContain(id);
      expect(idsFor(true)).not.toContain(id);
    },
  );

  it("keeps unmarked shortcuts in both layouts", () => {
    const unmarked = KEYBOARD_SHORTCUTS.filter((s) => !s.availability).map(
      (s) => s.id,
    );
    const inLayout = new Set(idsFor(true));
    const outOfLayout = new Set(idsFor(false));
    for (const id of unmarked) {
      expect(inLayout.has(id)).toBe(true);
      expect(outOfLayout.has(id)).toBe(true);
    }
  });

  it("defaults to the non-channels layout", () => {
    expect(
      Object.values(getShortcutsByCategory())
        .flat()
        .map((s) => s.id),
    ).toEqual(idsFor(false));
  });
});

describe("SHORTCUTS", () => {
  // The Electron View menu binds CmdOrCtrl+0 to "Actual Size" in the main
  // process, which a renderer preventDefault can't reliably beat.
  it("leaves mod+0 to the host's reset-zoom accelerator", () => {
    expect(SHORTCUTS.SWITCH_STARRED_CHANNEL.split(",")).not.toContain("mod+0");
    expect(SHORTCUTS.RESET_ZOOM).toBe("mod+0");
  });

  it("offers nine channel slots", () => {
    expect(SHORTCUTS.SWITCH_STARRED_CHANNEL.split(",")).toHaveLength(9);
  });
});
