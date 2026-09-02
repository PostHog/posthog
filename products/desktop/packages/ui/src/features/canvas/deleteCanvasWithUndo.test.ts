import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const deleteMutate = vi.fn().mockResolvedValue(undefined);
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@posthog/ui/features/canvas/hostClient", () => ({
  hostClient: () => ({ dashboards: { delete: { mutate: deleteMutate } } }),
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
    dismiss: vi.fn(),
  },
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import {
  CANVAS_DELETE_UNDO_MS,
  deleteCanvasWithUndo,
} from "@posthog/ui/features/canvas/deleteCanvasWithUndo";
import { usePendingCanvasDeleteStore } from "@posthog/ui/features/canvas/stores/pendingCanvasDeleteStore";

function schedule(invalidate = vi.fn()) {
  deleteCanvasWithUndo({
    dashboardId: "d1",
    channelId: "c1",
    name: "Weekly report",
    surface: "dashboards_grid",
    invalidate,
  });
  return invalidate;
}

// The Undo button handed to the toast.
function undo(): () => void {
  const options = toastSuccess.mock.calls.at(-1)?.[1] as {
    action: { onClick: () => void };
  };
  return options.action.onClick;
}

function isPending(id: string): boolean {
  return !!usePendingCanvasDeleteStore.getState().pending[id];
}

describe("deleteCanvasWithUndo", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    usePendingCanvasDeleteStore.setState({ pending: {} });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("hides the canvas immediately but sends nothing until the window closes", async () => {
    const invalidate = schedule();

    expect(isPending("d1")).toBe(true);
    expect(deleteMutate).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(CANVAS_DELETE_UNDO_MS);

    expect(deleteMutate).toHaveBeenCalledWith({ id: "d1" });
    expect(invalidate).toHaveBeenCalled();
    expect(isPending("d1")).toBe(false);
  });

  it("undo cancels the delete outright — nothing is sent", async () => {
    schedule();
    undo()();

    expect(isPending("d1")).toBe(false);

    await vi.advanceTimersByTimeAsync(CANVAS_DELETE_UNDO_MS * 2);

    expect(deleteMutate).not.toHaveBeenCalled();
  });

  it("restores the canvas and toasts when the delete fails", async () => {
    deleteMutate.mockRejectedValueOnce(new Error("host offline"));
    schedule();

    await vi.advanceTimersByTimeAsync(CANVAS_DELETE_UNDO_MS);

    expect(isPending("d1")).toBe(false);
    expect(toastError).toHaveBeenCalledWith(
      "Couldn't delete canvas",
      expect.objectContaining({ description: "host offline" }),
    );
  });

  it("re-deleting the same canvas restarts the window instead of stacking commits", async () => {
    schedule();
    await vi.advanceTimersByTimeAsync(CANVAS_DELETE_UNDO_MS / 2);
    schedule();
    await vi.advanceTimersByTimeAsync(CANVAS_DELETE_UNDO_MS);

    expect(deleteMutate).toHaveBeenCalledTimes(1);
  });
});
