import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { act, renderHook } from "@testing-library/react";
import type { MouseEvent, PointerEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useInboxReportSelectionStore } from "../stores/inboxReportSelectionStore";
import { SELECTION_HOLD_MS } from "../utils/reportSelection";
import { useInboxReportCardSelection } from "./useInboxReportCardSelection";

const track = vi.fn();
vi.mock("@posthog/ui/shell/analytics", () => ({
  track: (...args: unknown[]) => track(...args),
}));

function pointerDownAt(x: number, y: number): PointerEvent {
  return {
    button: 0,
    clientX: x,
    clientY: y,
    shiftKey: false,
    metaKey: false,
    ctrlKey: false,
  } as PointerEvent;
}

function clickWith(
  modifiers: Partial<Pick<MouseEvent, "shiftKey" | "metaKey" | "ctrlKey">> = {},
): MouseEvent & { preventDefault: ReturnType<typeof vi.fn> } {
  return {
    shiftKey: false,
    metaKey: false,
    ctrlKey: false,
    ...modifiers,
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
  } as unknown as MouseEvent & { preventDefault: ReturnType<typeof vi.fn> };
}

function selectedIds(): string[] {
  return useInboxReportSelectionStore.getState().selectedReportIds;
}

describe("useInboxReportCardSelection", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    track.mockClear();
    useInboxReportSelectionStore.setState({
      selectedReportIds: [],
      lastClickedId: null,
      orderedReportIds: ["r1", "r2", "r3"],
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("selects the card after a press and hold, and swallows the hold's own click", () => {
    const { result } = renderHook(() =>
      useInboxReportCardSelection("r2", true),
    );

    act(() => {
      result.current.cardHandlers.onPointerDown(pointerDownAt(10, 10));
    });
    expect(result.current.isHolding).toBe(true);

    act(() => {
      vi.advanceTimersByTime(SELECTION_HOLD_MS);
    });
    expect(selectedIds()).toEqual(["r2"]);
    expect(result.current.isHolding).toBe(false);
    expect(track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.INBOX_SELECTION_MODE_ENTERED,
      { entry_method: "long_press" },
    );

    // The pointerup that ends the hold fires a click, which must not open the report.
    const click = clickWith();
    act(() => {
      result.current.cardHandlers.onClickCapture(click);
    });
    expect(click.preventDefault).toHaveBeenCalled();
    expect(selectedIds()).toEqual(["r2"]);
  });

  it("cancels a hold that travels further than the tolerance, so a scroll never selects", () => {
    const { result } = renderHook(() =>
      useInboxReportCardSelection("r2", true),
    );

    act(() => {
      result.current.cardHandlers.onPointerDown(pointerDownAt(10, 10));
      result.current.cardHandlers.onPointerMove(pointerDownAt(10, 40));
      vi.advanceTimersByTime(SELECTION_HOLD_MS);
    });

    expect(selectedIds()).toEqual([]);
    expect(result.current.isHolding).toBe(false);
  });

  it("leaves a plain click alone until something is selected", () => {
    const { result } = renderHook(() =>
      useInboxReportCardSelection("r2", true),
    );

    const click = clickWith();
    act(() => {
      result.current.cardHandlers.onClickCapture(click);
    });

    expect(click.preventDefault).not.toHaveBeenCalled();
    expect(selectedIds()).toEqual([]);
  });

  it("toggles on a plain click once the list is in selection mode", () => {
    useInboxReportSelectionStore.setState({ selectedReportIds: ["r1"] });
    const { result } = renderHook(() =>
      useInboxReportCardSelection("r2", true),
    );

    const click = clickWith();
    act(() => {
      result.current.cardHandlers.onClickCapture(click);
    });

    expect(click.preventDefault).toHaveBeenCalled();
    expect(selectedIds()).toEqual(["r1", "r2"]);
    // Selection mode was already on, so this is not a new entry.
    expect(track).not.toHaveBeenCalled();
  });

  it("ranges a shift-click over the published list order", () => {
    useInboxReportSelectionStore.setState({
      selectedReportIds: ["r1"],
      lastClickedId: "r1",
    });
    const { result } = renderHook(() =>
      useInboxReportCardSelection("r3", true),
    );

    act(() => {
      result.current.cardHandlers.onClickCapture(clickWith({ shiftKey: true }));
    });

    expect(selectedIds()).toEqual(["r1", "r2", "r3"]);
  });

  it("does nothing on a card the list marks unselectable", () => {
    const { result } = renderHook(() =>
      useInboxReportCardSelection("r2", false),
    );

    const click = clickWith({ metaKey: true });
    act(() => {
      result.current.cardHandlers.onPointerDown(pointerDownAt(10, 10));
      vi.advanceTimersByTime(SELECTION_HOLD_MS);
      result.current.cardHandlers.onClickCapture(click);
    });

    expect(selectedIds()).toEqual([]);
    expect(click.preventDefault).not.toHaveBeenCalled();
  });
});
