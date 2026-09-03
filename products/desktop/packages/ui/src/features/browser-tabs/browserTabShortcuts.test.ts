import { describe, expect, it } from "vitest";
import { shouldHandleBrowserTabSwitch } from "./browserTabShortcuts";

describe("shouldHandleBrowserTabSwitch", () => {
  it("leaves Ctrl+digit to inner task tabs on macOS", () => {
    expect(
      shouldHandleBrowserTabSwitch({ ctrlKey: true, metaKey: false }, true),
    ).toBe(false);
  });

  it("handles Ctrl+digit as the browser shortcut off macOS", () => {
    expect(
      shouldHandleBrowserTabSwitch({ ctrlKey: true, metaKey: false }, false),
    ).toBe(true);
  });

  it("handles Cmd+digit on macOS", () => {
    expect(
      shouldHandleBrowserTabSwitch({ ctrlKey: false, metaKey: true }, true),
    ).toBe(true);
  });
});
