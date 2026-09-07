import { describe, expect, it } from "vitest";
import {
  cycledTabId,
  shouldHandleBrowserTabSwitch,
} from "./browserTabShortcuts";

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

describe("cycledTabId", () => {
  const ids = ["a", "b", "c"];

  it("steps forward and wraps past the last tab", () => {
    expect(cycledTabId(ids, "b", 1)).toBe("c");
    expect(cycledTabId(ids, "c", 1)).toBe("a");
  });

  it("steps back and wraps past the first tab", () => {
    expect(cycledTabId(ids, "b", -1)).toBe("a");
    expect(cycledTabId(ids, "a", -1)).toBe("c");
  });

  it("has nowhere to go with a single tab", () => {
    expect(cycledTabId(["a"], "a", 1)).toBeNull();
    expect(cycledTabId([], null, 1)).toBeNull();
  });

  // The active tab is derived from history state, which can briefly name a tab
  // the strip has not rendered yet; a press then enters at the near end.
  it("enters at the near end when the active tab is unknown", () => {
    expect(cycledTabId(ids, null, 1)).toBe("a");
    expect(cycledTabId(ids, "gone", -1)).toBe("c");
  });
});
