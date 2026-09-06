import { describe, expect, it } from "vitest";
import {
  formatHotkeyParts,
  getShortcutsByCategory,
  KEYBOARD_SHORTCUTS,
  panelTabShortcut,
  SHORTCUTS,
} from "./keyboard-shortcuts";

function idsFor(channelsLayout: boolean): string[] {
  return Object.values(getShortcutsByCategory({ channelsLayout }))
    .flat()
    .map((s) => s.id);
}

describe("getShortcutsByCategory", () => {
  it("advertises tab switching only in the channels layout", () => {
    expect(idsFor(true)).toContain("switch-browser-tab");
    expect(idsFor(false)).not.toContain("switch-browser-tab");
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
  it("registers the task detail archive shortcut", () => {
    expect(SHORTCUTS.ARCHIVE_TASK).toBe("mod+shift+a");
    expect(KEYBOARD_SHORTCUTS).toContainEqual(
      expect.objectContaining({
        id: "archive-task",
        keys: SHORTCUTS.ARCHIVE_TASK,
        context: "Task detail",
      }),
    );
  });

  // The Electron View menu binds CmdOrCtrl+0 to "Actual Size" in the main
  // process, which a renderer preventDefault can't reliably beat.
  it("leaves mod+0 to the host's reset-zoom accelerator", () => {
    expect(SHORTCUTS.SWITCH_STARRED_CHANNEL.split(",")).not.toContain("mod+0");
    expect(SHORTCUTS.RESET_ZOOM).toBe("mod+0");
  });

  it("offers nine channel slots", () => {
    expect(SHORTCUTS.SWITCH_STARRED_CHANNEL.split(",")).toHaveLength(9);
  });

  it("keeps browser and inner-panel tab shortcuts distinct off macOS", () => {
    expect(panelTabShortcut(true)).toBe(
      "ctrl+1,ctrl+2,ctrl+3,ctrl+4,ctrl+5,ctrl+6,ctrl+7,ctrl+8,ctrl+9",
    );
    expect(panelTabShortcut(false)).toBe(
      "alt+1,alt+2,alt+3,alt+4,alt+5,alt+6,alt+7,alt+8,alt+9",
    );
  });

  // react-hotkeys-hook splits a hotkey string on "," (alternatives) and then
  // on "+" (the keys in one combination). A dangling separator - a trailing
  // "," or "+" - produces an empty-string key, which used to make SETTINGS
  // ("mod+,") register a second, degenerate hotkey that matched bare
  // modifier keydowns (Right Shift, the Windows key).
  it("never splits into an empty key token", () => {
    for (const value of Object.values(SHORTCUTS)) {
      for (const alternative of value.split(",")) {
        expect(alternative.split("+")).not.toContain("");
      }
    }
  });

  it("still displays settings as a comma, not the key name", () => {
    expect(formatHotkeyParts(SHORTCUTS.SETTINGS)).toContain(",");
  });
});
