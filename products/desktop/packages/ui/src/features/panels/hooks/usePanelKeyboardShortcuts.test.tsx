import { fireEvent, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({
  track: vi.fn(),
  setActiveTaskContext: vi.fn(),
}));

import { usePanelLayoutStore } from "../panelLayoutStore";
import { usePanelKeyboardShortcuts } from "./usePanelKeyboardShortcuts";

function press(init: KeyboardEventInit) {
  fireEvent.keyDown(document.body, init);
  fireEvent.keyUp(document.body, init);
}

describe("usePanelKeyboardShortcuts", () => {
  beforeEach(() => {
    // The app runs these scoped hotkeys without a HotkeysProvider, which
    // react-hotkeys-hook accepts with a warning on every registration.
    vi.spyOn(console, "warn").mockImplementation(() => {});
    usePanelLayoutStore.getState().clearAllLayouts();
    usePanelLayoutStore.getState().initializeTask("task-1");
  });

  it("splits the focused pane to the right on mod+\\ and closes it on mod+shift+w", () => {
    renderHook(() => usePanelKeyboardShortcuts("task-1"));

    press({ key: "\\", ctrlKey: true });
    const split = usePanelLayoutStore.getState().getLayout("task-1");
    expect(split?.panelTree.type).toBe("group");
    expect(split?.focusedPanelId).not.toBe("main-panel");

    press({ key: "w", ctrlKey: true, shiftKey: true });
    const closed = usePanelLayoutStore.getState().getLayout("task-1");
    expect(closed?.panelTree).toMatchObject({ type: "leaf", id: "main-panel" });
    expect(closed?.focusedPanelId).toBe("main-panel");
  });
});
