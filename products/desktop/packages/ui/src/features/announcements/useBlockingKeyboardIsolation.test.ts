import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useBlockingKeyboardIsolation } from "./useBlockingKeyboardIsolation";

// Real key events start at the focused element and bubble up through
// document to window; the hook intercepts them on the way down (capture).
function pressKey() {
  document.body.dispatchEvent(
    new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }),
  );
}

describe("useBlockingKeyboardIsolation", () => {
  it("starves document-level shortcut listeners while active, restores on unmount", () => {
    const shortcut = vi.fn();
    document.addEventListener("keydown", shortcut);

    pressKey();
    expect(shortcut).toHaveBeenCalledTimes(1);

    const { unmount } = renderHook(() => useBlockingKeyboardIsolation(true));
    pressKey();
    expect(shortcut).toHaveBeenCalledTimes(1);

    unmount();
    pressKey();
    expect(shortcut).toHaveBeenCalledTimes(2);

    document.removeEventListener("keydown", shortcut);
  });

  it("does nothing while inactive", () => {
    const shortcut = vi.fn();
    document.addEventListener("keydown", shortcut);

    renderHook(() => useBlockingKeyboardIsolation(false));
    pressKey();
    expect(shortcut).toHaveBeenCalledTimes(1);

    document.removeEventListener("keydown", shortcut);
  });
});
