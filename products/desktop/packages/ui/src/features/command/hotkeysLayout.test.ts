import { renderHook } from "@testing-library/react";
import { useHotkeys } from "react-hotkeys-hook";
import { describe, expect, it, vi } from "vitest";

// Regression guard for patches/react-hotkeys-hook.patch. Single-letter shortcuts must match the
// layout-aware event.key, not the physical event.code. On a Dvorak layout the key labelled "c"
// sits at the physical QWERTY-"I" slot (event.code "KeyI"), which used to trigger the "mod+i"
// Inbox shortcut and hijack Cmd+C.
function press(init: KeyboardEventInit): void {
  document.dispatchEvent(
    new KeyboardEvent("keydown", { bubbles: true, ...init }),
  );
}

describe("react-hotkeys-hook layout-aware matching", () => {
  it("fires mod+i when the logical key is i", () => {
    const onInbox = vi.fn();
    renderHook(() =>
      useHotkeys("mod+i", onInbox, { enableOnContentEditable: true }),
    );

    press({ key: "i", code: "KeyI", metaKey: true });

    expect(onInbox).toHaveBeenCalledTimes(1);
  });

  it("does not fire mod+i on a Dvorak Cmd+C that lands on the physical KeyI slot", () => {
    const onInbox = vi.fn();
    renderHook(() =>
      useHotkeys("mod+i", onInbox, { enableOnContentEditable: true }),
    );

    press({ key: "c", code: "KeyI", metaKey: true });

    expect(onInbox).not.toHaveBeenCalled();
  });
});
