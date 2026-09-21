import { describe, expect, it } from "vitest";
import { acceleratorFromEvent } from "./QuickAskShortcutSetting";

describe("acceleratorFromEvent", () => {
  it.each([
    // Each physical modifier keeps its own identity instead of collapsing into
    // CommandOrControl, which Electron would resolve to the wrong key.
    [
      "macOS Control stays Control",
      { code: "Space", ctrlKey: true },
      true,
      "Control+Space",
    ],
    [
      "macOS Command stays Command",
      { code: "Space", metaKey: true },
      true,
      "Command+Space",
    ],
    [
      "macOS Command+Control keeps both",
      { code: "Space", metaKey: true, ctrlKey: true },
      true,
      "Command+Control+Space",
    ],
    [
      "non-mac Meta becomes Super",
      { code: "Space", metaKey: true },
      false,
      "Super+Space",
    ],
    [
      "non-mac Control stays Control",
      { code: "Space", ctrlKey: true },
      false,
      "Control+Space",
    ],
    ["Alt keeps its key", { code: "KeyP", altKey: true }, true, "Alt+P"],
  ] as const)("%s", (_name, init, isMac, expected) => {
    const event = new KeyboardEvent("keydown", init);
    expect(acceleratorFromEvent(event, isMac)).toBe(expected);
  });
});
