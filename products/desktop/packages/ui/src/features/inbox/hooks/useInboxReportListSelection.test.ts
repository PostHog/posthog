import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useInboxReportSelectionStore } from "@posthog/ui/features/inbox/stores/inboxReportSelectionStore";
import { SELECTION_HOLD_MS } from "@posthog/ui/features/inbox/utils/reportSelection";
import { act, renderHook } from "@testing-library/react";
import type { MouseEvent, PointerEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ track: vi.fn() }));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: mocks.track }));

import { useInboxReportListSelection } from "./useInboxReportListSelection";

const ORDERED_IDS = ["r1", "r2", "r3"];

function press(overrides: Partial<PointerEvent> = {}): PointerEvent {
  return {
    button: 0,
    shiftKey: false,
    metaKey: false,
    ctrlKey: false,
    clientX: 100,
    clientY: 100,
    ...overrides,
  } as PointerEvent;
}

function click(overrides: Partial<MouseEvent> = {}): MouseEvent {
  return {
    shiftKey: false,
    metaKey: false,
    ctrlKey: false,
    preventDefault: vi.fn(),
    ...overrides,
  } as unknown as MouseEvent;
}

function selectedIds(): string[] {
  return useInboxReportSelectionStore.getState().selectedReportIds;
}

describe("useInboxReportListSelection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    useInboxReportSelectionStore.setState({
      selectedReportIds: [],
      lastClickedId: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("selects on a press and hold, and the click that ends the hold does not open the report", () => {
    const { result, rerender } = renderHook(() =>
      useInboxReportListSelection(ORDERED_IDS),
    );

    act(() => {
      result.current
        .getReportSelection("r2")
        .holdHandlers.onPointerDown(press());
      vi.advanceTimersByTime(SELECTION_HOLD_MS);
    });

    expect(selectedIds()).toEqual(["r2"]);
    expect(mocks.track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.INBOX_SELECTION_MODE_ENTERED,
      { entry_method: "long_press" },
    );

    rerender();
    const event = click();
    act(() => {
      result.current.getReportSelection("r2").onClick(event);
    });

    expect(event.preventDefault).toHaveBeenCalled();
    expect(selectedIds()).toEqual(["r2"]);
  });

  it("cancels the hold when the pointer travels, so a scroll never selects", () => {
    const { result } = renderHook(() =>
      useInboxReportListSelection(ORDERED_IDS),
    );

    act(() => {
      const { holdHandlers } = result.current.getReportSelection("r2");
      holdHandlers.onPointerDown(press());
      holdHandlers.onPointerMove(press({ clientY: 140 }));
      vi.advanceTimersByTime(SELECTION_HOLD_MS);
    });

    expect(selectedIds()).toEqual([]);
  });

  it("lets a plain click through to the report until something is selected, then toggles", () => {
    const { result, rerender } = renderHook(() =>
      useInboxReportListSelection(ORDERED_IDS),
    );

    const opening = click();
    act(() => {
      result.current.getReportSelection("r1").onClick(opening);
    });

    expect(opening.preventDefault).not.toHaveBeenCalled();
    expect(selectedIds()).toEqual([]);

    act(() => {
      result.current.getReportSelection("r1").toggle("checkbox");
    });
    rerender();

    const toggling = click();
    act(() => {
      result.current.getReportSelection("r3").onClick(toggling);
    });

    expect(toggling.preventDefault).toHaveBeenCalled();
    expect(selectedIds()).toEqual(["r1", "r3"]);
  });

  it("ranges over the rendered order on a shift-click", () => {
    const { result, rerender } = renderHook(() =>
      useInboxReportListSelection(ORDERED_IDS),
    );

    act(() => {
      result.current.getReportSelection("r1").toggle("checkbox");
    });
    rerender();
    act(() => {
      result.current
        .getReportSelection("r3")
        .onClick(click({ shiftKey: true }));
    });

    expect(result.current.orderedSelectedIds).toEqual(["r1", "r2", "r3"]);
  });

  it("records the entry method only for the report that opens an empty selection", () => {
    const { result, rerender } = renderHook(() =>
      useInboxReportListSelection(ORDERED_IDS),
    );

    act(() => {
      result.current.getReportSelection("r1").toggle("checkbox");
    });
    rerender();
    act(() => {
      result.current.getReportSelection("r2").toggle("checkbox");
    });

    expect(mocks.track).toHaveBeenCalledTimes(1);
  });

  it("drops reports that left the list, so a bulk action cannot reach them", () => {
    const { rerender } = renderHook(
      ({ ids }) => useInboxReportListSelection(ids),
      { initialProps: { ids: ORDERED_IDS } },
    );

    act(() => {
      useInboxReportSelectionStore.setState({
        selectedReportIds: ["r1", "r3"],
      });
    });
    rerender({ ids: ["r1", "r2"] });

    expect(selectedIds()).toEqual(["r1"]);
  });

  it.each([
    ["clears the selection on Escape", "div", []],
    ["leaves Escape to the field being typed in", "input", ["r1"]],
  ])("%s", (_label, tag, expected) => {
    renderHook(() => useInboxReportListSelection(ORDERED_IDS));
    act(() => {
      useInboxReportSelectionStore.setState({ selectedReportIds: ["r1"] });
    });

    const target = document.createElement(tag);
    document.body.appendChild(target);
    act(() => {
      target.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    });

    expect(selectedIds()).toEqual(expected);
  });
});
