import { ToastProvider } from "@posthog/quill";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CANVAS_DELETE_UNDO_MS,
  deleteCanvasWithUndo,
} from "./deleteCanvasWithUndo";
import { usePendingCanvasDeleteStore } from "./stores/pendingCanvasDeleteStore";

vi.mock("@posthog/ui/features/canvas/hostClient", () => ({
  hostClient: vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: { getState: () => ({ toastNotifications: true }) },
}));

describe("board delete Undo", () => {
  afterEach(() => vi.useRealTimers());

  it.each(["Undo", "timeout"])(
    "closes the focused toast after %s",
    async (action) => {
      vi.useFakeTimers();
      const remove = vi.fn().mockResolvedValue(undefined);
      render(<ToastProvider>{null}</ToastProvider>);
      act(() => {
        deleteCanvasWithUndo({
          dashboardId: "board-toast-test",
          channelId: "space",
          name: "Test board",
          surface: "dashboards_grid",
          remove,
        });
      });

      const undo = screen.getByText("Undo");
      act(() => undo.focus());
      if (action === "Undo") fireEvent.click(undo);
      await act(() => vi.advanceTimersByTimeAsync(CANVAS_DELETE_UNDO_MS * 2));

      expect(remove).toHaveBeenCalledTimes(action === "Undo" ? 0 : 1);
      expect(usePendingCanvasDeleteStore.getState().pending).toEqual({});
      expect(screen.queryByText("Undo")).toBeNull();
    },
  );
});
