import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TabShortcutFallback } from "./TabShortcutFallback";

function pressCloseTab(): KeyboardEvent {
  const event = new KeyboardEvent("keydown", {
    key: "w",
    code: "KeyW",
    metaKey: true,
    bubbles: true,
    cancelable: true,
  });
  document.dispatchEvent(event);
  return event;
}

describe("TabShortcutFallback", () => {
  // Without a preventDefault here the key reaches Electron's Window ▸ Close
  // role and takes the window — and everything unsaved in it — with it.
  it("swallows Cmd+W so the host menu never sees it", () => {
    render(<TabShortcutFallback enabled />);
    expect(pressCloseTab().defaultPrevented).toBe(true);
  });

  // Disabled is how the BrowserTabStrip keeps ownership where it is mounted.
  it("leaves the key alone when disabled", () => {
    render(<TabShortcutFallback enabled={false} />);
    expect(pressCloseTab().defaultPrevented).toBe(false);
  });
});
